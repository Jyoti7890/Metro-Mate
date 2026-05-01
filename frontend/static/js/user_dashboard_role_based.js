const userDashboardCharts = {};

const currencyFormatter = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
});

const numberFormatter = new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 0,
});

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
});

async function loadDashboard(withLoadingState) {
    const authToken = localStorage.getItem('auth_token');
    const refreshButton = document.getElementById('refresh-dashboard');

    if (withLoadingState && refreshButton) {
        refreshButton.disabled = true;
        refreshButton.textContent = 'Refreshing...';
    }

    try {
        const response = await fetch('/api/dashboard/user', {
            headers: {
                Authorization: `Bearer ${authToken}`,
            },
        });

        if (response.status === 401) {
            handleSessionExpiry();
            return;
        }

        if (response.status === 403) {
            window.location.replace('/admin');
            return;
        }

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(payload.detail || 'Unable to load dashboard.');
        }

        const data = await response.json();
        renderDashboard(data);
        setError('');
    } catch (error) {
        setError(error.message || 'Unable to load dashboard right now.');
    } finally {
        if (refreshButton) {
            refreshButton.disabled = false;
            refreshButton.textContent = 'Refresh';
        }
    }
}

function renderDashboard(data) {
    const lastUpdated = document.getElementById('last-updated');
    if (lastUpdated) {
        lastUpdated.textContent = formatDateTime(data.generated_at);
    }

    renderProfile(data.profile);
    renderOverview(data.overview);
    renderTicketHistory(data.ticket_history);
    renderLostFound(data.lost_and_found);
    renderInsights(data.smart_insights);
    renderSmartCard(data.smart_card);
    renderCharts(data.charts);
}

function renderProfile(profile) {
    const container = document.getElementById('profile-summary');
    if (!container) return;

    const items = [
        ['Name', profile?.name || 'Not available'],
        ['Email', profile?.email || 'Not available'],
        ['User ID', profile?.user_id || 'Not available'],
        ['Last Login', formatDateTime(profile?.last_login_time)],
        ['Role', capitalize(profile?.role || 'user')],
        ['Account Status', capitalize(profile?.account_status || 'active')],
    ];

    container.innerHTML = items.map(([label, value]) => `
        <div class="profile-item">
            <span class="profile-label">${escapeHtml(label)}</span>
            <span class="font-semibold">${escapeHtml(String(value))}</span>
        </div>
    `).join('');
}

function renderOverview(overview) {
    const container = document.getElementById('overview-grid');
    if (!container) return;

    const cards = [
        { label: 'Total Tickets', value: formatNumber(overview?.total_tickets_booked || 0) },
        { label: 'Amount Spent', value: formatCurrency(overview?.total_amount_spent || 0) },
        { label: 'Upcoming Tickets', value: formatNumber(overview?.upcoming_tickets || 0) },
        { label: 'Active Complaints', value: formatNumber(overview?.active_complaints || 0) },
        { label: 'Smart Card Balance', value: formatCurrency(overview?.smart_card_balance || 0) },
    ];

    container.innerHTML = cards.map((card) => `
        <div class="info-card">
            <div class="muted-copy">${escapeHtml(card.label)}</div>
            <div class="metric-value">${escapeHtml(String(card.value))}</div>
        </div>
    `).join('');
}

function renderTicketHistory(ticketHistory) {
    const tableBody = document.getElementById('ticket-history-body');
    if (!tableBody) return;

    if (!ticketHistory?.length) {
        tableBody.innerHTML = `<tr><td colspan="6">${emptyState('No ticket history yet.')}</td></tr>`;
        return;
    }

    tableBody.innerHTML = ticketHistory.map((ticket) => `
        <tr>
            <td>${escapeHtml(ticket.from_station || '-')}</td>
            <td>${escapeHtml(ticket.to_station || '-')}</td>
            <td>${formatDateTime(ticket.travel_date)}</td>
            <td>${formatCurrency(ticket.fare || 0)}</td>
            <td>${formatNumber(ticket.ticket_count || 0)}</td>
            <td><span class="status-pill ${statusClass(ticket.status)}">${escapeHtml(ticket.status || 'Completed')}</span></td>
        </tr>
    `).join('');
}

function renderLostFound(lostFound) {
    const summaryGrid = document.getElementById('complaint-summary-grid');
    const tableBody = document.getElementById('complaints-body');
    const summary = lostFound?.summary || {};

    if (summaryGrid) {
        const cards = [
            ['Total Complaints', formatNumber(summary.total_complaints || 0)],
            ['Active', formatNumber(summary.active_complaints || 0)],
            ['Matched', formatNumber(summary.matched_complaints || 0)],
            ['Resolved', formatNumber(summary.resolved_complaints || 0)],
        ];

        summaryGrid.innerHTML = cards.map(([label, value]) => `
            <div class="info-card">
                <div class="muted-copy">${escapeHtml(label)}</div>
                <div class="metric-value" style="font-size: 1.2rem;">${escapeHtml(String(value))}</div>
            </div>
        `).join('');
    }

    if (!tableBody) return;
    if (!lostFound?.complaints?.length) {
        tableBody.innerHTML = `<tr><td colspan="6">${emptyState('No lost and found complaints yet.')}</td></tr>`;
        return;
    }

    tableBody.innerHTML = lostFound.complaints.map((complaint) => `
        <tr>
            <td>${escapeHtml(complaint.complaint_id || '-')}</td>
            <td>${escapeHtml(complaint.item_name || '-')}</td>
            <td>${escapeHtml(complaint.station || '-')}</td>
            <td>${formatDateTime(complaint.submitted_at)}</td>
            <td><span class="status-pill ${statusClass(complaint.status)}">${escapeHtml(complaint.status || 'Pending')}</span></td>
            <td>${formatNumber(complaint.match_count || 0)}</td>
        </tr>
    `).join('');
}

function renderInsights(insights) {
    const note = document.getElementById('insight-note');
    const routesList = document.getElementById('routes-list');

    if (note) {
        note.innerHTML = `
            <div class="font-bold">Peak Travel Window</div>
            <p class="muted-copy" style="margin: 0.45rem 0 0.7rem;">${escapeHtml(insights?.travel_pattern_note || 'No insights yet.')}</p>
            <div class="font-semibold">${escapeHtml(insights?.peak_travel_window || 'Insufficient history')}</div>
        `;
    }

    if (!routesList) return;
    if (!insights?.suggested_frequent_routes?.length) {
        routesList.innerHTML = emptyState('Suggested frequent routes will appear once enough booking history exists.');
        return;
    }

    routesList.innerHTML = insights.suggested_frequent_routes.map((route) => `
        <div class="insight-card">
            <div class="font-bold">${escapeHtml(route.route || 'Route')}</div>
            <p class="muted-copy" style="margin-top: 0.35rem;">${escapeHtml(route.message || '')}</p>
            <div style="margin-top: 0.65rem;" class="font-semibold">${formatNumber(route.bookings || 0)} bookings</div>
        </div>
    `).join('');
}

function renderSmartCard(card) {
    const summaryGrid = document.getElementById('smart-card-summary');
    const tableBody = document.getElementById('transactions-body');

    if (summaryGrid) {
        const cards = [
            ['Card Number', card?.card_number_masked || 'Not available'],
            ['Balance', formatCurrency(card?.balance || 0)],
            ['Recent Transactions', formatNumber(card?.recent_transactions?.length || 0)],
        ];

        summaryGrid.innerHTML = cards.map(([label, value]) => `
            <div class="info-card">
                <div class="muted-copy">${escapeHtml(label)}</div>
                <div class="metric-value" style="font-size: 1.15rem;">${escapeHtml(String(value))}</div>
            </div>
        `).join('');
    }

    if (!tableBody) return;
    if (!card?.recent_transactions?.length) {
        tableBody.innerHTML = `<tr><td colspan="4">${emptyState('No smart card transactions yet.')}</td></tr>`;
        return;
    }

    tableBody.innerHTML = card.recent_transactions.map((transaction) => `
        <tr>
            <td><span class="status-pill ${statusClass(transaction.type)}">${escapeHtml(capitalize(transaction.type || ''))}</span></td>
            <td>${formatCurrency(transaction.amount || 0)}</td>
            <td>${escapeHtml(transaction.from_station || '-')}${transaction.to_station ? ` -> ${escapeHtml(transaction.to_station)}` : ''}</td>
            <td>${formatDateTime(transaction.created_at)}</td>
        </tr>
    `).join('');
}

function renderCharts(charts) {
    if (typeof Chart === 'undefined') {
        setError('Chart.js could not be loaded.');
        return;
    }

    const palette = {
        primary: cssVar('--primary'),
        accent: cssVar('--accent'),
        info: cssVar('--info'),
        success: cssVar('--success'),
        warning: cssVar('--warning'),
        destructive: cssVar('--destructive'),
    };

    renderBasicChart('monthly-bookings-chart', 'bar', charts?.monthly_booking_trend, {
        label: 'Bookings',
        color: palette.accent,
    });
    renderBasicChart('monthly-spend-chart', 'line', charts?.monthly_spend_trend, {
        label: 'Spend',
        color: palette.info,
        fill: true,
    });
    renderBasicChart('stations-chart', 'bar', charts?.station_frequency, {
        label: 'Usage',
        color: palette.primary,
        indexAxis: 'y',
    });
    renderBasicChart('peak-hours-chart', 'bar', charts?.peak_travel_times, {
        label: 'Trips',
        color: palette.success,
    });
    renderBasicChart('complaint-status-chart', 'doughnut', charts?.complaint_status, {
        label: 'Complaints',
        multiColor: [palette.info, palette.warning, palette.success, palette.destructive],
    });
}

function renderBasicChart(canvasId, type, rows, options) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    destroyChart(canvasId);
    const safeRows = Array.isArray(rows) ? rows : [];

    userDashboardCharts[canvasId] = new Chart(canvas, {
        type,
        data: {
            labels: safeRows.map((row) => row.label),
            datasets: [
                {
                    label: options.label,
                    data: safeRows.map((row) => row.value),
                    backgroundColor: options.multiColor || buildSeriesColors(safeRows.length, options.color),
                    borderColor: options.multiColor || options.color,
                    borderWidth: 2,
                    tension: 0.35,
                    fill: options.fill || false,
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

function destroyChart(id) {
    if (userDashboardCharts[id]) {
        userDashboardCharts[id].destroy();
        delete userDashboardCharts[id];
    }
}

function buildSeriesColors(count, baseColor) {
    return Array.from({ length: Math.max(count, 1) }, (_, index) => {
        const opacity = Math.max(0.28, 0.9 - (index * 0.08));
        return hexToRgba(baseColor, opacity);
    });
}

function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#2563eb';
}

function statusClass(value) {
    return `status-${String(value || 'pending').trim().toLowerCase().replace(/\s+/g, '-')}`;
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
        dateStyle: 'medium',
        timeStyle: 'short',
    });
}

function capitalize(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function emptyState(message) {
    return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function setError(message) {
    const panel = document.getElementById('dashboard-error');
    if (!panel) return;
    panel.textContent = message;
    panel.classList.toggle('hidden', !message);
}

function handleSessionExpiry() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user_id');
    localStorage.removeItem('user_email');
    localStorage.removeItem('user_name');
    localStorage.removeItem('user_type');
    window.location.replace('/');
}

function hexToRgba(hex, opacity) {
    const safeHex = String(hex || '#2563eb').replace('#', '');
    const normalized = safeHex.length === 3
        ? safeHex.split('').map((chunk) => chunk + chunk).join('')
        : safeHex.padEnd(6, '0').slice(0, 6);
    const numeric = Number.parseInt(normalized, 16);
    const r = (numeric >> 16) & 255;
    const g = (numeric >> 8) & 255;
    const b = numeric & 255;
    return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}
