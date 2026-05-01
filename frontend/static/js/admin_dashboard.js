const adminCharts = {};
let adminDashboardData = null;

const adminCurrencyFormatter = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
});

const adminNumberFormatter = new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 0,
});

document.addEventListener('DOMContentLoaded', () => {
    const authToken = localStorage.getItem('auth_token');
    const userType = (localStorage.getItem('user_type') || '').trim().toLowerCase();

    if (!authToken) {
        window.location.replace('/');
        return;
    }

    if (userType && userType !== 'admin') {
        window.location.replace('/home');
        return;
    }

    const refreshButton = document.getElementById('refresh-admin-dashboard');
    const stationForm = document.getElementById('station-form');
    const stationReset = document.getElementById('station-reset');

    if (refreshButton) {
        refreshButton.addEventListener('click', () => loadAdminDashboard(true));
    }
    if (stationForm) {
        stationForm.addEventListener('submit', submitStationForm);
    }
    if (stationReset) {
        stationReset.addEventListener('click', resetStationForm);
    }

    loadAdminDashboard(true);
});

async function loadAdminDashboard(withLoadingState) {
    const authToken = localStorage.getItem('auth_token');
    const refreshButton = document.getElementById('refresh-admin-dashboard');

    if (withLoadingState && refreshButton) {
        refreshButton.disabled = true;
        refreshButton.textContent = 'Refreshing...';
    }

    try {
        const response = await fetch('/api/dashboard/admin', {
            headers: {
                Authorization: `Bearer ${authToken}`,
            },
        });

        if (response.status === 401) {
            clearAdminSession();
            return;
        }
        if (response.status === 403) {
            window.location.replace('/home');
            return;
        }
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(payload.detail || 'Unable to load admin dashboard.');
        }

        adminDashboardData = await response.json();
        renderAdminDashboard(adminDashboardData);
        setAdminError('');
    } catch (error) {
        setAdminError(error.message || 'Unable to load admin dashboard right now.');
    } finally {
        if (refreshButton) {
            refreshButton.disabled = false;
            refreshButton.textContent = 'Refresh';
        }
    }
}

function renderAdminDashboard(data) {
    const updated = document.getElementById('admin-last-updated');
    if (updated) {
        updated.textContent = formatAdminDateTime(data.generated_at);
    }

    renderOverviewCards(data.system_overview);
    renderAdminCharts(data.global_analytics);
    renderUsersTable(data.user_management);
    renderStationsTable(data.station_management?.stations || []);
    renderComplaintsTable(
        data.lost_found_management?.complaints || [],
        data.lost_found_management?.available_found_items || [],
    );
    renderInsights(data.advanced_insights);
}

function renderOverviewCards(overview) {
    const container = document.getElementById('overview-grid');
    if (!container) return;

    const cards = [
        ['Total Users', formatAdminNumber(overview?.total_users || 0)],
        ['Total Bookings', formatAdminNumber(overview?.total_bookings || 0)],
        ['Total Revenue', formatAdminCurrency(overview?.total_revenue || 0)],
        ['Total Complaints', formatAdminNumber(overview?.total_complaints || 0)],
    ];

    container.innerHTML = cards.map(([label, value]) => `
        <div class="metric-card">
            <div class="muted-copy">${escapeHtml(label)}</div>
            <div class="metric-value">${escapeHtml(String(value))}</div>
        </div>
    `).join('');
}

function renderAdminCharts(analytics) {
    if (typeof Chart === 'undefined') {
        setAdminError('Chart.js is unavailable, so analytics charts could not be rendered.');
        return;
    }

    const palette = {
        primary: cssVar('--primary'),
        accent: cssVar('--accent'),
        info: cssVar('--info'),
        success: cssVar('--success'),
        warning: cssVar('--warning'),
    };

    renderAdminChart('daily-bookings-chart', 'bar', analytics?.daily_bookings_trend, {
        label: 'Bookings',
        color: palette.accent,
    });
    renderAdminChart('revenue-chart', 'line', analytics?.revenue_analysis, {
        label: 'Revenue',
        color: palette.info,
        fill: true,
    });
    renderAdminChart('crowded-stations-chart', 'bar', analytics?.most_crowded_stations, {
        label: 'Usage',
        color: palette.primary,
        indexAxis: 'y',
    });
    renderAdminChart('peak-hours-chart', 'bar', analytics?.peak_hours_analysis, {
        label: 'Trips',
        color: palette.success,
    });
}

function renderAdminChart(canvasId, type, rows, options) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    destroyAdminChart(canvasId);
    const safeRows = Array.isArray(rows) ? rows : [];

    adminCharts[canvasId] = new Chart(canvas, {
        type,
        data: {
            labels: safeRows.map((row) => row.label),
            datasets: [
                {
                    label: options.label,
                    data: safeRows.map((row) => row.value),
                    backgroundColor: buildSeriesColors(safeRows.length, options.color),
                    borderColor: options.color,
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
                    display: type !== 'bar' || Boolean(options.fill),
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

function renderUsersTable(users) {
    const tableBody = document.getElementById('users-table-body');
    if (!tableBody) return;

    if (!users?.length) {
        tableBody.innerHTML = `<tr><td colspan="7">${emptyAdminState('No users available.')}</td></tr>`;
        return;
    }

    tableBody.innerHTML = users.map((user) => {
        const nextStatus = user.status === 'active' ? 'blocked' : 'active';
        const nextLabel = user.status === 'active' ? 'Deactivate' : 'Activate';
        return `
            <tr>
                <td>${escapeHtml(user.name || 'Unknown')}</td>
                <td>${escapeHtml(user.email || '-')}</td>
                <td>${escapeHtml(capitalize(user.role || 'user'))}</td>
                <td><span class="status-pill ${statusClass(user.status)}">${escapeHtml(capitalize(user.status || 'active'))}</span></td>
                <td>${formatAdminNumber(user.total_bookings || 0)}</td>
                <td>${formatAdminCurrency(user.total_spend || 0)}</td>
                <td>
                    <div class="flex gap-2" style="flex-wrap: wrap;">
                        <button class="btn btn-outline btn-sm" data-user-details="${escapeHtml(user.user_id)}">View</button>
                        <button class="btn btn-primary btn-sm" data-user-status="${escapeHtml(user.user_id)}" data-next-status="${escapeHtml(nextStatus)}">${escapeHtml(nextLabel)}</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    tableBody.querySelectorAll('[data-user-details]').forEach((button) => {
        button.addEventListener('click', () => loadUserDetails(button.getAttribute('data-user-details')));
    });
    tableBody.querySelectorAll('[data-user-status]').forEach((button) => {
        button.addEventListener('click', () => updateUserStatus(
            button.getAttribute('data-user-status'),
            button.getAttribute('data-next-status'),
        ));
    });
}

async function loadUserDetails(userId) {
    const panel = document.getElementById('selected-user-panel');
    if (!panel) return;

    panel.innerHTML = 'Loading user details...';
    try {
        const response = await fetch(`/api/admin/users/${userId}`, {
            headers: {
                Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
            },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.detail || 'Unable to load user details.');
        }

        panel.innerHTML = `
            <div class="section-head" style="margin-bottom: 0.75rem;">
                <div>
                    <h3 class="font-bold">${escapeHtml(payload.user?.name || 'User')}</h3>
                    <p class="muted-copy">${escapeHtml(payload.user?.email || '-')}</p>
                </div>
                <span class="status-pill ${statusClass(payload.user?.status)}">${escapeHtml(capitalize(payload.user?.status || 'active'))}</span>
            </div>
            <div class="form-grid" style="margin-bottom: 1rem;">
                <div class="metric-card"><div class="muted-copy">Role</div><div class="font-semibold">${escapeHtml(capitalize(payload.user?.role || 'user'))}</div></div>
                <div class="metric-card"><div class="muted-copy">Last Login</div><div class="font-semibold">${escapeHtml(formatAdminDateTime(payload.user?.last_login_time))}</div></div>
                <div class="metric-card"><div class="muted-copy">Recent Bookings</div><div class="font-semibold">${formatAdminNumber(payload.summary?.recent_booking_count || 0)}</div></div>
                <div class="metric-card"><div class="muted-copy">Recent Complaints</div><div class="font-semibold">${formatAdminNumber(payload.summary?.recent_complaint_count || 0)}</div></div>
            </div>
            <div class="split-grid" style="grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));">
                <div class="insight-card">
                    <div class="font-bold">Recent Bookings</div>
                    <div class="control-stack" style="margin-top: 0.75rem;">
                        ${renderDetailList(
                            payload.recent_bookings,
                            (booking) => `${escapeHtml(booking.from_station || '-')} -> ${escapeHtml(booking.to_station || '-')}`,
                            (booking) => `${formatAdminCurrency(booking.total_fare || 0)} • ${escapeHtml(capitalize(booking.status || 'active'))} • ${formatAdminDateTime(booking.booking_date)}`
                        )}
                    </div>
                </div>
                <div class="insight-card">
                    <div class="font-bold">Recent Complaints</div>
                    <div class="control-stack" style="margin-top: 0.75rem;">
                        ${renderDetailList(
                            payload.recent_complaints,
                            (complaint) => `${escapeHtml(complaint.item_name || 'Complaint')} • ${escapeHtml(complaint.station || '-')}`,
                            (complaint) => `${escapeHtml(capitalize(complaint.status || 'pending'))} • ${formatAdminDateTime(complaint.submitted_at)}`
                        )}
                    </div>
                </div>
            </div>
        `;
    } catch (error) {
        panel.innerHTML = `<div class="empty-state">${escapeHtml(error.message || 'Unable to load user details.')}</div>`;
    }
}

function renderDetailList(items, titleBuilder, metaBuilder) {
    if (!items?.length) {
        return '<div class="empty-state">No recent records.</div>';
    }
    return items.map((item) => `
        <div class="metric-card">
            <div class="font-semibold">${titleBuilder(item)}</div>
            <div class="muted-copy" style="margin-top: 0.35rem;">${metaBuilder(item)}</div>
        </div>
    `).join('');
}

async function updateUserStatus(userId, status) {
    try {
        const response = await fetch(`/api/admin/users/${userId}/status`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
            },
            body: JSON.stringify({ status }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.detail || 'Unable to update user status.');
        }
        await loadAdminDashboard(false);
    } catch (error) {
        setAdminError(error.message || 'Unable to update user status.');
    }
}

function renderStationsTable(stations) {
    const tableBody = document.getElementById('stations-table-body');
    if (!tableBody) return;

    if (!stations?.length) {
        tableBody.innerHTML = `<tr><td colspan="5">${emptyAdminState('No stations configured yet.')}</td></tr>`;
        return;
    }

    tableBody.innerHTML = stations.map((station) => `
        <tr>
            <td>${escapeHtml(station.name || '-')}</td>
            <td>${escapeHtml(station.line || '-')}</td>
            <td>${formatAdminNumber(station.sequence || 0)}${station.is_interchange ? ' • Interchange' : ''}</td>
            <td>${escapeHtml(station.station_type || 'residential')}</td>
            <td>
                <div class="flex gap-2" style="flex-wrap: wrap;">
                    <button class="btn btn-outline btn-sm" data-edit-station="${escapeHtml(station.station_id)}">Edit</button>
                    <button class="btn btn-primary btn-sm" data-delete-station="${escapeHtml(station.station_id)}">Delete</button>
                </div>
            </td>
        </tr>
    `).join('');

    tableBody.querySelectorAll('[data-edit-station]').forEach((button) => {
        button.addEventListener('click', () => fillStationForm(button.getAttribute('data-edit-station')));
    });
    tableBody.querySelectorAll('[data-delete-station]').forEach((button) => {
        button.addEventListener('click', () => deleteStation(button.getAttribute('data-delete-station')));
    });
}

function fillStationForm(stationId) {
    const station = (adminDashboardData?.station_management?.stations || []).find((item) => item.station_id === stationId);
    if (!station) return;

    document.getElementById('station-id').value = station.station_id || '';
    document.getElementById('station-name').value = station.name || '';
    document.getElementById('station-line').value = station.line || '';
    document.getElementById('station-sequence').value = station.sequence || 0;
    document.getElementById('station-type').value = station.station_type || 'residential';
    document.getElementById('station-color').value = station.line_color || '#0f1a27';
    document.getElementById('station-interchange').checked = Boolean(station.is_interchange);
    document.getElementById('station-elevated').checked = Boolean(station.is_elevated);
}

function resetStationForm() {
    document.getElementById('station-id').value = '';
    document.getElementById('station-form')?.reset();
    document.getElementById('station-sequence').value = 0;
    document.getElementById('station-type').value = 'residential';
    document.getElementById('station-color').value = '#0f1a27';
}

async function submitStationForm(event) {
    event.preventDefault();
    const stationId = document.getElementById('station-id').value;
    const payload = {
        name: document.getElementById('station-name').value.trim(),
        line: document.getElementById('station-line').value.trim(),
        sequence: Number(document.getElementById('station-sequence').value || 0),
        station_type: document.getElementById('station-type').value.trim() || 'residential',
        line_color: document.getElementById('station-color').value.trim() || '#0f1a27',
        is_interchange: document.getElementById('station-interchange').checked,
        is_elevated: document.getElementById('station-elevated').checked,
    };

    const url = stationId ? `/api/admin/stations/${stationId}` : '/api/admin/stations';
    const method = stationId ? 'PATCH' : 'POST';

    try {
        const response = await fetch(url, {
            method,
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
            },
            body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || 'Unable to save station.');
        }
        resetStationForm();
        await loadAdminDashboard(false);
    } catch (error) {
        setAdminError(error.message || 'Unable to save station.');
    }
}

async function deleteStation(stationId) {
    if (!window.confirm('Delete this station from the system?')) {
        return;
    }

    try {
        const response = await fetch(`/api/admin/stations/${stationId}`, {
            method: 'DELETE',
            headers: {
                Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
            },
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || 'Unable to delete station.');
        }
        await loadAdminDashboard(false);
    } catch (error) {
        setAdminError(error.message || 'Unable to delete station.');
    }
}

function renderComplaintsTable(complaints, foundItems) {
    const tableBody = document.getElementById('complaints-table-body');
    if (!tableBody) return;

    if (!complaints?.length) {
        tableBody.innerHTML = `<tr><td colspan="6">${emptyAdminState('No complaints found.')}</td></tr>`;
        return;
    }

    const foundItemOptions = foundItems.map((item) => `
        <option value="${escapeHtml(item.found_item_id)}">${escapeHtml(item.item_name || 'Found item')} • ${escapeHtml(item.station || '-')}</option>
    `).join('');

    tableBody.innerHTML = complaints.map((complaint) => `
        <tr>
            <td>${escapeHtml(complaint.complaint_id || '-')}</td>
            <td>${escapeHtml(complaint.user_name || complaint.user_email || 'Unknown User')}</td>
            <td>${escapeHtml(complaint.item_name || '-')}</td>
            <td><span class="status-pill ${statusClass(complaint.status)}">${escapeHtml(capitalize(complaint.status || 'pending'))}</span></td>
            <td>
                <div class="flex gap-2" style="flex-wrap: wrap;">
                    <select class="form-input" data-complaint-status="${escapeHtml(complaint.complaint_id)}" style="min-width: 130px;">
                        ${['Pending', 'Matched', 'Resolved'].map((status) => `
                            <option value="${status}" ${status === complaint.status ? 'selected' : ''}>${status}</option>
                        `).join('')}
                    </select>
                    <button class="btn btn-outline btn-sm" data-save-complaint="${escapeHtml(complaint.complaint_id)}">Save</button>
                </div>
            </td>
            <td>
                <div class="flex gap-2" style="flex-wrap: wrap;">
                    <select class="form-input" data-complaint-match="${escapeHtml(complaint.complaint_id)}" style="min-width: 190px;">
                        <option value="">Select found item</option>
                        ${foundItemOptions}
                    </select>
                    <button class="btn btn-primary btn-sm" data-match-complaint="${escapeHtml(complaint.complaint_id)}">Match</button>
                </div>
            </td>
        </tr>
    `).join('');

    tableBody.querySelectorAll('[data-save-complaint]').forEach((button) => {
        button.addEventListener('click', () => saveComplaintStatus(button.getAttribute('data-save-complaint')));
    });
    tableBody.querySelectorAll('[data-match-complaint]').forEach((button) => {
        button.addEventListener('click', () => matchComplaint(button.getAttribute('data-match-complaint')));
    });
}

async function saveComplaintStatus(complaintId) {
    const select = document.querySelector(`[data-complaint-status="${complaintId}"]`);
    if (!select) return;

    try {
        const response = await fetch(`/api/admin/complaints/${complaintId}/status`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
            },
            body: JSON.stringify({ status: select.value }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || 'Unable to update complaint status.');
        }
        await loadAdminDashboard(false);
    } catch (error) {
        setAdminError(error.message || 'Unable to update complaint status.');
    }
}

async function matchComplaint(complaintId) {
    const select = document.querySelector(`[data-complaint-match="${complaintId}"]`);
    if (!select || !select.value) {
        setAdminError('Select a found item before matching.');
        return;
    }

    try {
        const response = await fetch(`/api/admin/complaints/${complaintId}/match`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
            },
            body: JSON.stringify({
                found_item_id: select.value,
                match_score: 0.9,
                status: 'pending',
            }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || 'Unable to create complaint match.');
        }
        await loadAdminDashboard(false);
    } catch (error) {
        setAdminError(error.message || 'Unable to create complaint match.');
    }
}

function renderInsights(insights) {
    const highRiskList = document.getElementById('high-risk-list');
    const crowdSummaryList = document.getElementById('crowd-summary-list');

    if (highRiskList) {
        const items = insights?.high_risk_stations || [];
        highRiskList.innerHTML = items.length
            ? items.map((item) => `
                <div class="metric-card">
                    <div class="font-semibold">${escapeHtml(item.label || 'Station')}</div>
                    <div class="muted-copy" style="margin-top: 0.35rem;">${formatAdminNumber(item.value || 0)} complaints</div>
                </div>
            `).join('')
            : emptyAdminState('No high-risk station signal yet.');
    }

    if (crowdSummaryList) {
        const items = insights?.crowd_prediction_summary || [];
        crowdSummaryList.innerHTML = items.length
            ? items.map((item) => `
                <div class="metric-card">
                    <div class="font-semibold">${escapeHtml(item.station || 'Station')}</div>
                    <div class="muted-copy" style="margin-top: 0.35rem;">${escapeHtml(item.peak_window || '-')} • Estimated load ${formatAdminNumber(item.estimated_load || 0)}</div>
                    <div class="muted-copy" style="margin-top: 0.35rem;">${escapeHtml(item.note || '')}</div>
                </div>
            `).join('')
            : emptyAdminState('No crowd summary available yet.');
    }
}

function destroyAdminChart(id) {
    if (adminCharts[id]) {
        adminCharts[id].destroy();
        delete adminCharts[id];
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

function formatAdminCurrency(value) {
    return adminCurrencyFormatter.format(Number(value || 0));
}

function formatAdminNumber(value) {
    return adminNumberFormatter.format(Number(value || 0));
}

function formatAdminDateTime(value) {
    if (!value) return 'Not available';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Not available';
    return parsed.toLocaleString('en-IN', {
        dateStyle: 'medium',
        timeStyle: 'short',
    });
}

function statusClass(value) {
    return `status-${String(value || 'pending').trim().toLowerCase().replace(/\s+/g, '-')}`;
}

function capitalize(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function setAdminError(message) {
    const panel = document.getElementById('admin-error');
    if (!panel) return;
    panel.textContent = message;
    panel.classList.toggle('hidden', !message);
}

function emptyAdminState(message) {
    return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function clearAdminSession() {
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
