const dashboardCharts = {};
const dashboardRefreshMs = 30000;
let refreshTimerId = null;

const currencyFormatter = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
});

const numberFormatter = new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 0,
});

const KPI_CONFIG = [
    { key: 'card_balance', label: 'Smart Card Balance', format: 'currency' },
    { key: 'active_tickets', label: 'Active Tickets Count', format: 'number' },
    { key: 'total_trips', label: 'Total Trips', format: 'number' },
    { key: 'total_amount_spent', label: 'Total Amount Spent', format: 'currency' },
    { key: 'monthly_spend', label: 'Monthly Spend', format: 'currency' },
    { key: 'active_complaints', label: 'Active Complaints', format: 'number' },
    { key: 'resolved_complaints', label: 'Resolved Complaints', format: 'number' },
    { key: 'last_booking_fare', label: 'Last Booking Fare', format: 'currency' },
    { key: 'favorite_source_station', label: 'Favorite Source Station', format: 'text' },
    { key: 'favorite_destination_station', label: 'Favorite Destination Station', format: 'text' },
    { key: 'most_used_payment_method', label: 'Most Used Payment Method', format: 'text' },
    { key: 'recharge_count', label: 'Recharge Count', format: 'number' },
    { key: 'total_recharge_amount', label: 'Total Recharge Amount', format: 'currency' },
    { key: 'last_recharge_amount', label: 'Last Recharge Amount', format: 'currency' },
    { key: 'last_travel_date', label: 'Last Travel Date', format: 'datetime' },
    { key: 'latest_active_booking', label: 'Latest Active Booking', format: 'route' },
];

document.addEventListener('DOMContentLoaded', () => {
    const authToken = localStorage.getItem('auth_token');
    const userType = (localStorage.getItem('user_type') || '').trim().toLowerCase();

    if (!authToken) {
        window.location.replace('/');
        return;
    }

    if (userType && userType !== 'user') {
        window.location.replace('/admin');
        return;
    }

    const refreshButton = document.getElementById('refresh-dashboard');
    if (refreshButton) {
        refreshButton.addEventListener('click', () => loadDashboard(true));
    }

    loadDashboard(true);
    refreshTimerId = window.setInterval(() => loadDashboard(false), dashboardRefreshMs);
    window.addEventListener('beforeunload', () => {
        if (refreshTimerId) {
            window.clearInterval(refreshTimerId);
        }
    });
});

async function loadDashboard(showLoadingState) {
    const authToken = localStorage.getItem('auth_token');
    if (!authToken) {
        clearDashboardSession();
        window.location.replace('/');
        return;
    }

    const refreshButton = document.getElementById('refresh-dashboard');
    if (showLoadingState && refreshButton) {
        refreshButton.disabled = true;
        refreshButton.textContent = 'Refreshing...';
    }

    try {
        const response = await fetch('/user-dashboard', {
            headers: {
                Authorization: `Bearer ${authToken}`,
            },
        });

        if (response.status === 401) {
            clearDashboardSession();
            window.location.replace('/');
            return;
        }

        if (response.status === 403) {
            window.location.replace('/admin');
            return;
        }

        if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({}));
            throw new Error(errorPayload.detail || 'Unable to load dashboard.');
        }

        const dashboardData = await response.json();
        renderDashboard(dashboardData);
        setDashboardError('');
    } catch (error) {
        console.error('Dashboard load failed:', error);
        setDashboardError(error.message || 'Unable to load dashboard right now.');
    } finally {
        if (refreshButton) {
            refreshButton.disabled = false;
            refreshButton.textContent = 'Refresh Now';
        }
    }
}

function renderDashboard(data) {
    const greeting = document.getElementById('dashboard-greeting');
    const subtitle = document.getElementById('dashboard-subtitle');
    const lastUpdated = document.getElementById('last-updated');

    if (greeting) {
        greeting.textContent = `${data.user.full_name || 'Metro Mate'}'s Personalized Dashboard`;
    }
    if (subtitle) {
        subtitle.textContent = `Fresh personalized travel, smart card, complaint, and activity insights for ${data.user.email}.`;
    }
    if (lastUpdated) {
        lastUpdated.textContent = formatDateTime(data.generated_at);
    }

    renderKpis(data.kpis);
    renderCharts(data.graphs);
    renderActiveTickets(data.active_tickets);
    renderBookingSummary(data.booking_summary, data.recent_bookings);
    renderSmartCard(data.smart_card, data.recent_transactions);
    renderComplaints(data.complaints);
    renderPredictions(data.predictions);
    renderRecommendations(data.recommendations);
    renderAlerts(data.alerts);
    renderActivity(data.recent_activity);
    renderQuickActions(data.quick_actions);
}

function renderKpis(kpis) {
    const kpiGrid = document.getElementById('kpi-grid');
    if (!kpiGrid) return;

    kpiGrid.innerHTML = KPI_CONFIG.map((config) => `
        <div class="metric-card">
            <div class="metric-label">${escapeHtml(config.label)}</div>
            <div class="metric-value">${formatKpiValue(kpis[config.key], config.format)}</div>
        </div>
    `).join('');
}

function renderCharts(graphs) {
    if (typeof Chart === 'undefined') {
        setDashboardError('Chart.js is unavailable, so analytics charts could not be rendered.');
        return;
    }

    const palette = buildChartPalette();

    renderSimpleChart('travel-history-chart', 'bar', graphs.travel_history, {
        label: 'Trips',
        color: palette.accent,
    });

    renderSimpleChart('spending-trend-chart', 'line', graphs.spending_trend, {
        label: 'Spend',
        color: palette.info,
        fill: true,
    });

    renderSimpleChart('most-used-stations-chart', 'bar', graphs.most_used_stations, {
        label: 'Trips',
        color: palette.primary,
    });

    renderSimpleChart('routes-chart', 'bar', graphs.routes, {
        label: 'Trips',
        color: palette.warning,
        indexAxis: 'y',
    });

    renderSimpleChart('payment-methods-chart', 'doughnut', graphs.payment_methods, {
        label: 'Payment methods',
        multiColor: [palette.accent, palette.info, palette.success, palette.warning, palette.destructive],
    });

    renderSimpleChart('time-of-day-chart', 'bar', graphs.time_of_day, {
        label: 'Trips',
        color: palette.success,
    });

    renderDualLineChart('smart-card-trend-chart', graphs.smart_card_trend, palette);

    renderSimpleChart('complaint-status-chart', 'doughnut', graphs.complaint_status, {
        label: 'Complaints',
        multiColor: [palette.warning, palette.info, palette.success, palette.destructive, palette.primary],
    });

    renderSimpleChart('weekday-weekend-chart', 'bar', graphs.weekday_vs_weekend, {
        label: 'Trips',
        color: palette.primary,
    });

    renderSimpleChart('fare-ranges-chart', 'bar', graphs.fare_ranges, {
        label: 'Bookings',
        color: palette.destructive,
    });
}

function renderSimpleChart(canvasId, type, rows, options) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    destroyChart(canvasId);
    const safeRows = Array.isArray(rows) ? rows : [];

    dashboardCharts[canvasId] = new Chart(canvas, {
        type,
        data: {
            labels: safeRows.map((row) => row.label),
            datasets: [
                {
                    label: options.label,
                    data: safeRows.map((row) => row.value),
                    backgroundColor: options.multiColor || buildSeriesColorArray(safeRows.length, options.color),
                    borderColor: options.multiColor || options.color,
                    borderWidth: 2,
                    fill: options.fill || false,
                    tension: 0.35,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: options.indexAxis || 'x',
            plugins: {
                legend: {
                    display: type === 'doughnut',
                },
            },
            scales: type === 'doughnut' ? {} : {
                y: {
                    beginAtZero: true,
                },
            },
        },
    });
}

function renderDualLineChart(canvasId, trend, palette) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    destroyChart(canvasId);
    const labels = Array.isArray(trend?.labels) ? trend.labels : [];
    const credit = Array.isArray(trend?.credit) ? trend.credit : [];
    const debit = Array.isArray(trend?.debit) ? trend.debit : [];

    dashboardCharts[canvasId] = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Credit',
                    data: credit,
                    borderColor: palette.success,
                    backgroundColor: hexToRgba(palette.success, 0.18),
                    fill: true,
                    tension: 0.35,
                },
                {
                    label: 'Debit',
                    data: debit,
                    borderColor: palette.destructive,
                    backgroundColor: hexToRgba(palette.destructive, 0.14),
                    fill: true,
                    tension: 0.35,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                },
            },
        },
    });
}

function buildChartPalette() {
    return {
        accent: getCssVar('--accent'),
        info: getCssVar('--info'),
        success: getCssVar('--success'),
        warning: getCssVar('--warning'),
        destructive: getCssVar('--destructive'),
        primary: getCssVar('--primary'),
    };
}

function destroyChart(canvasId) {
    if (dashboardCharts[canvasId]) {
        dashboardCharts[canvasId].destroy();
        delete dashboardCharts[canvasId];
    }
}

function renderActiveTickets(activeTickets) {
    const container = document.getElementById('active-tickets-list');
    if (!container) return;

    if (!activeTickets?.length) {
        container.innerHTML = emptyState('No active tickets right now.');
        return;
    }

    container.innerHTML = activeTickets.map((ticket) => `
        <div class="info-row">
            <div>
                <div class="font-bold">${escapeHtml(ticket.from_station || 'Unknown')} -> ${escapeHtml(ticket.to_station || 'Unknown')}</div>
                <div class="helper-text">${formatDateTime(ticket.booking_date)} • ${escapeHtml(ticket.payment_method || 'Unknown')}</div>
                <div class="helper-text">${ticket.ticket_count || 0} ticket(s) • ${formatCurrency(ticket.total_fare)}</div>
            </div>
            <div class="text-right">
                <span class="status-pill ${statusClass(ticket.status)}">${escapeHtml(ticket.status || 'active')}</span>
                <div style="margin-top: 0.75rem;">
                    <a href="/my-bookings" class="btn btn-outline btn-sm">View Ticket</a>
                </div>
            </div>
        </div>
    `).join('');
}

function renderBookingSummary(summary, recentBookings) {
    const summaryGrid = document.getElementById('booking-summary-grid');
    const tableBody = document.getElementById('recent-bookings-table');
    if (summaryGrid) {
        const items = [
            { label: 'Total Bookings', value: formatNumber(summary?.total_bookings || 0) },
            { label: 'Active', value: formatNumber(summary?.active_bookings || 0) },
            { label: 'Cancelled', value: formatNumber(summary?.cancelled_bookings || 0) },
            { label: 'Completed', value: formatNumber(summary?.completed_bookings || 0) },
            { label: 'Next Active Ticket', value: summary?.next_active_ticket?.route || 'No active ticket' },
            { label: 'Latest Active Route', value: summary?.latest_active_route || 'No route available' },
        ];
        summaryGrid.innerHTML = items.map((item) => `
            <div class="metric-card">
                <div class="metric-label">${escapeHtml(item.label)}</div>
                <div class="metric-value" style="font-size: 1.05rem;">${escapeHtml(String(item.value))}</div>
            </div>
        `).join('');
    }

    if (!tableBody) return;
    if (!recentBookings?.length) {
        tableBody.innerHTML = `<tr><td colspan="5">${emptyState('No booking history yet.')}</td></tr>`;
        return;
    }

    tableBody.innerHTML = recentBookings.map((booking) => `
        <tr>
            <td>${escapeHtml(booking.from_station || 'Unknown')} -> ${escapeHtml(booking.to_station || 'Unknown')}</td>
            <td>${formatDateTime(booking.booking_date)}</td>
            <td>${formatCurrency(booking.total_fare)}</td>
            <td>${formatNumber(booking.ticket_count || 0)}</td>
            <td><span class="status-pill ${statusClass(booking.status)}">${escapeHtml(booking.status || 'unknown')}</span></td>
        </tr>
    `).join('');
}

function renderSmartCard(smartCard, transactions) {
    const summaryGrid = document.getElementById('smart-card-summary');
    const tableBody = document.getElementById('transactions-table');

    if (summaryGrid) {
        const items = [
            { label: 'Card Number', value: smartCard?.card_number_masked || 'Not available' },
            { label: 'Current Balance', value: formatCurrency(smartCard?.current_balance || 0) },
            { label: 'Recharge Count', value: formatNumber(smartCard?.total_recharge_count || 0) },
            { label: 'Recharge Amount', value: formatCurrency(smartCard?.total_recharge_amount || 0) },
            { label: 'Debit Amount', value: formatCurrency(smartCard?.total_debit_amount || 0) },
            { label: 'Avg Spend / Trip', value: formatCurrency(smartCard?.average_spend_per_trip || 0) },
            { label: 'Last Recharge', value: formatDateTime(smartCard?.last_recharge_date) },
            { label: 'Recharge Suggestion', value: formatCurrency(smartCard?.recharge_suggestion || 0) },
        ];
        summaryGrid.innerHTML = items.map((item) => `
            <div class="metric-card">
                <div class="metric-label">${escapeHtml(item.label)}</div>
                <div class="metric-value" style="font-size: 1.05rem;">${escapeHtml(String(item.value))}</div>
            </div>
        `).join('');
    }

    if (!tableBody) return;
    if (!transactions?.length) {
        tableBody.innerHTML = `<tr><td colspan="4">${emptyState('No smart card transactions yet.')}</td></tr>`;
        return;
    }

    tableBody.innerHTML = transactions.map((transaction) => `
        <tr>
            <td><span class="status-pill ${statusClass(transaction.type)}">${escapeHtml(transaction.type || 'unknown')}</span></td>
            <td>${formatCurrency(transaction.amount)}</td>
            <td>${escapeHtml(transaction.from_station || '-')}${transaction.to_station ? ` -> ${escapeHtml(transaction.to_station)}` : ''}</td>
            <td>${formatDateTime(transaction.created_at)}</td>
        </tr>
    `).join('');
}

function renderComplaints(complaints) {
    const summaryGrid = document.getElementById('complaint-summary-grid');
    const complaintsList = document.getElementById('complaints-list');
    const matchesList = document.getElementById('matches-list');

    if (summaryGrid) {
        const summary = complaints?.summary || {};
        const items = [
            { label: 'Total Complaints', value: formatNumber(summary.total_complaints || 0) },
            { label: 'Active Complaints', value: formatNumber(summary.active_complaints || 0) },
            { label: 'Resolved Complaints', value: formatNumber(summary.resolved_complaints || 0) },
            { label: 'Latest Complaint', value: summary.latest_complaint?.item_name || 'No complaints' },
        ];
        summaryGrid.innerHTML = items.map((item) => `
            <div class="metric-card">
                <div class="metric-label">${escapeHtml(item.label)}</div>
                <div class="metric-value" style="font-size: 1.05rem;">${escapeHtml(String(item.value))}</div>
            </div>
        `).join('');
    }

    if (complaintsList) {
        if (!complaints?.recent?.length) {
            complaintsList.innerHTML = emptyState('No complaint history found.');
        } else {
            complaintsList.innerHTML = complaints.recent.map((complaint) => `
                <div class="info-row">
                    <div>
                        <div class="font-bold">${escapeHtml(complaint.item_name || 'Unnamed item')}</div>
                        <div class="helper-text">${escapeHtml(complaint.station || 'Unknown station')} • ${formatDateTime(complaint.created_at)}</div>
                    </div>
                    <span class="status-pill ${statusClass(complaint.status)}">${escapeHtml(complaint.status || 'unknown')}</span>
                </div>
            `).join('');
        }
    }

    if (matchesList) {
        if (!complaints?.potential_matches?.length) {
            matchesList.innerHTML = emptyState('No potential matches yet.');
        } else {
            matchesList.innerHTML = complaints.potential_matches.map((match) => `
                <div class="info-row">
                    <div>
                        <div class="font-bold">${escapeHtml(match.found_item?.item_name || 'Matched item')}</div>
                        <div class="helper-text">${escapeHtml(match.found_item?.station || 'Unknown station')} • Confidence ${escapeHtml(String(match.match_confidence))}%</div>
                    </div>
                    <span class="status-pill ${statusClass(match.status)}">${escapeHtml(match.status || 'pending')}</span>
                </div>
            `).join('');
        }
    }
}

function renderPredictions(predictions) {
    renderInsightCards('predictions-grid', predictions, 'confidence');
}

function renderRecommendations(recommendations) {
    const container = document.getElementById('recommendations-grid');
    if (!container) return;
    if (!recommendations?.length) {
        container.innerHTML = emptyState('Recommendations will appear as your travel history grows.');
        return;
    }

    container.innerHTML = recommendations.map((recommendation) => `
        <div class="insight-card">
            <div class="font-bold">${escapeHtml(recommendation.title || 'Recommendation')}</div>
            <p class="helper-text" style="margin: 0.5rem 0 0.75rem;">${escapeHtml(recommendation.description || '')}</p>
            <a href="${escapeHtml(recommendation.action_href || '/dashboard')}" class="btn btn-outline btn-sm">${escapeHtml(recommendation.action_label || 'Open')}</a>
        </div>
    `).join('');
}

function renderAlerts(alerts) {
    const container = document.getElementById('alerts-list');
    if (!container) return;
    if (!alerts?.length) {
        container.innerHTML = emptyState('No alerts right now.');
        return;
    }

    container.innerHTML = alerts.map((alert) => `
        <div class="alert-item ${escapeHtml(alert.severity || 'neutral')}">
            <div class="font-bold">${escapeHtml(alert.title || 'Alert')}</div>
            <p class="helper-text" style="margin: 0.5rem 0 0.75rem;">${escapeHtml(alert.message || '')}</p>
            <a href="${escapeHtml(alert.action_href || '/dashboard')}" class="btn btn-outline btn-sm">Open</a>
        </div>
    `).join('');
}

function renderActivity(activity) {
    const container = document.getElementById('activity-list');
    if (!container) return;
    if (!activity?.length) {
        container.innerHTML = emptyState('No recent activity yet.');
        return;
    }

    container.innerHTML = activity.map((item) => `
        <div class="activity-item">
            <div class="font-bold">${escapeHtml(item.title || 'Activity')}</div>
            <p class="helper-text" style="margin: 0.35rem 0;">${escapeHtml(item.description || '')}</p>
            <div class="helper-text">${formatDateTime(item.created_at)}</div>
        </div>
    `).join('');
}

function renderQuickActions(actions) {
    const container = document.getElementById('quick-actions-grid');
    if (!container) return;
    container.innerHTML = (actions || []).map((action) => `
        <a class="quick-action" href="${escapeHtml(action.href || '/dashboard')}">
            <span class="font-bold">${escapeHtml(action.label || 'Open')}</span>
            <span class="helper-text">Go</span>
        </a>
    `).join('');
}

function renderInsightCards(containerId, items, badgeField) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!items?.length) {
        container.innerHTML = emptyState('No insights available yet.');
        return;
    }

    container.innerHTML = items.map((item) => `
        <div class="insight-card">
            <div class="font-bold">${escapeHtml(item.title || 'Insight')}</div>
            <div class="metric-value" style="font-size: 1.05rem; margin-top: 0.6rem;">${formatInsightValue(item.value)}</div>
            <p class="helper-text" style="margin-top: 0.5rem;">${escapeHtml(item.description || '')}</p>
            ${badgeField && item[badgeField] ? `<div class="helper-text" style="margin-top: 0.75rem;">Confidence: ${escapeHtml(String(item[badgeField]))}%</div>` : ''}
        </div>
    `).join('');
}

function formatKpiValue(value, format) {
    if (format === 'currency') return formatCurrency(value);
    if (format === 'number') return formatNumber(value);
    if (format === 'datetime') return formatDateTime(value);
    if (format === 'route') return escapeHtml(value?.route || 'No active booking');
    return escapeHtml(value == null ? 'N/A' : String(value));
}

function formatInsightValue(value) {
    if (typeof value === 'number') {
        return Number.isInteger(value) ? formatNumber(value) : formatCurrency(value);
    }
    return escapeHtml(value == null ? 'N/A' : String(value));
}

function formatCurrency(value) {
    return currencyFormatter.format(Number(value || 0));
}

function formatNumber(value) {
    return numberFormatter.format(Number(value || 0));
}

function formatDateTime(value) {
    if (!value) return 'Not available';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Not available';
    return parsed.toLocaleString('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function statusClass(status) {
    return `status-${String(status || 'neutral').trim().toLowerCase().replace(/\s+/g, '-')}`;
}

function emptyState(message) {
    return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function setDashboardError(message) {
    const errorPanel = document.getElementById('dashboard-error');
    if (!errorPanel) return;
    if (!message) {
        errorPanel.classList.add('hidden-panel');
        errorPanel.textContent = '';
        return;
    }

    errorPanel.classList.remove('hidden-panel');
    errorPanel.textContent = message;
}

function clearDashboardSession() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user_id');
    localStorage.removeItem('user_email');
    localStorage.removeItem('user_name');
    localStorage.removeItem('user_type');
}

function getCssVar(variableName) {
    return getComputedStyle(document.documentElement).getPropertyValue(variableName).trim() || '#999999';
}

function buildSeriesColorArray(length, baseColor) {
    return Array.from({ length }, (_, index) => {
        const alpha = Math.max(0.25, 0.9 - (index * 0.08));
        return hexToRgba(baseColor, alpha);
    });
}

function hexToRgba(hex, alpha) {
    const safeHex = String(hex || '').replace('#', '').trim();
    if (safeHex.length !== 6) return `rgba(100, 100, 100, ${alpha})`;
    const red = parseInt(safeHex.slice(0, 2), 16);
    const green = parseInt(safeHex.slice(2, 4), 16);
    const blue = parseInt(safeHex.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}
