/* script.js — Lógica del dashboard parking-edge */

"use strict";

let _role = null;
let _socket = null;
const MAX_EVENTS = 100;

// ── Utilidades DOM ─────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const show = id => $(id).classList.remove("hidden");
const hide = id => $(id).classList.add("hidden");

function formatTime(isoStr) {
  if (!isoStr) return "—";
  try {
    return new Date(isoStr).toLocaleTimeString("es-CO", { hour12: false });
  } catch { return isoStr; }
}

function pct(val) {
  return val != null ? (val * 100).toFixed(0) + "%" : "—";
}

// ── Login ──────────────────────────────────────────────────────────────────

$("login-form").addEventListener("submit", async e => {
  e.preventDefault();
  const username = $("username").value.trim();
  const password = $("password").value;
  const errEl = $("login-error");
  errEl.classList.add("hidden");

  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error || "Error de autenticación";
      errEl.classList.remove("hidden");
      return;
    }
    _role = data.role;
    onLoginSuccess(data.username, data.role);
  } catch (err) {
    errEl.textContent = "Error de red";
    errEl.classList.remove("hidden");
  }
});

function onLoginSuccess(username, role) {
  hide("login-screen");
  show("dashboard-screen");
  $("user-badge").textContent = `${username} · ${role}`;

  if (role === "operator" || role === "admin") show("barrier-section");
  if (role === "admin") show("whitelist-section");

  connectSocket();
  loadEvents();
  loadWhitelistStats();
  if (role === "admin") loadWhitelist();
}

$("logout-btn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  location.reload();
});

// ── Socket.IO ──────────────────────────────────────────────────────────────

function connectSocket() {
  _socket = io({ path: "/ws" });

  _socket.on("connect", () => {
    $("mqtt-status").className = "status-dot online";
    $("mqtt-status").title = "MQTT conectado";
  });

  _socket.on("disconnect", () => {
    $("mqtt-status").className = "status-dot offline";
    $("mqtt-status").title = "MQTT desconectado";
  });

  _socket.on("mqtt_event", ({ topic, payload }) => {
    handleMqttEvent(topic, payload);
  });
}

function handleMqttEvent(topic, payload) {
  if (topic.includes("access_granted") || topic.includes("access_denied")) {
    prependEvent({
      created_at:   payload.timestamp,
      plate:        payload.payload?.plate || "—",
      lane_id:      payload.payload?.lane_id || "—",
      decision:     topic.includes("granted") ? "GRANTED" : "DENIED",
      reason:       payload.payload?.reason || "—",
      confidence:   payload.payload?.confidence,
    });
  }
}

// ── Eventos ────────────────────────────────────────────────────────────────

async function loadEvents() {
  try {
    const res  = await fetch("/api/events?limit=50");
    const rows = await res.json();
    const tbody = $("events-body");
    tbody.innerHTML = "";
    rows.forEach(r => appendEventRow(tbody, r));
    updateEventCount(rows.length);
  } catch { /* tabla vacía */ }
}

function prependEvent(ev) {
  const tbody = $("events-body");
  const row = buildEventRow(ev);
  tbody.insertBefore(row, tbody.firstChild);

  // Limitar filas en DOM
  while (tbody.rows.length > MAX_EVENTS) {
    tbody.deleteRow(tbody.rows.length - 1);
  }
  updateEventCount(tbody.rows.length);
  updateStats();
}

function appendEventRow(tbody, ev) {
  tbody.appendChild(buildEventRow(ev));
}

function buildEventRow(ev) {
  const tr = document.createElement("tr");
  const decisionClass = ev.decision === "GRANTED" ? "decision-granted" : "decision-denied";
  tr.innerHTML = `
    <td>${formatTime(ev.created_at)}</td>
    <td><strong>${ev.plate || "—"}</strong></td>
    <td>${ev.lane_id || "—"}</td>
    <td class="${decisionClass}">${ev.decision || "—"}</td>
    <td>${ev.reason || "—"}</td>
    <td>${pct(ev.confidence)}</td>
  `;
  return tr;
}

function updateEventCount(n) {
  $("event-count").textContent = n;
}

// ── Estadísticas ───────────────────────────────────────────────────────────

function updateStats() {
  const rows = $("events-body").rows;
  let granted = 0, denied = 0;
  for (const row of rows) {
    const decision = row.cells[3]?.textContent || "";
    if (decision === "GRANTED") granted++;
    else if (decision === "DENIED") denied++;
  }
  $("stat-granted").textContent = granted;
  $("stat-denied").textContent  = denied;
}

async function loadWhitelistStats() {
  try {
    const res  = await fetch("/api/whitelist");
    if (!res.ok) return;
    const data = await res.json();
    $("stat-whitelist").textContent = data.length;
  } catch { /* no actualizar */ }
}

// ── Control de barrera ─────────────────────────────────────────────────────

window.sendBarrier = async function (action) {
  const fb = $("barrier-feedback");
  fb.textContent = `Enviando ${action}...`;
  try {
    const res  = await fetch("/api/barrier", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await res.json();
    if (res.ok) {
      fb.textContent = `✓ Comando ${action} enviado (trace: ${data.trace_id?.slice(0, 8)})`;
    } else {
      fb.textContent = `✗ Error: ${data.error}`;
    }
  } catch {
    fb.textContent = "✗ Error de red";
  }
};

// ── Whitelist ──────────────────────────────────────────────────────────────

async function loadWhitelist() {
  try {
    const res  = await fetch("/api/whitelist");
    const rows = await res.json();
    const tbody = $("whitelist-body");
    tbody.innerHTML = "";
    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${r.plate}</strong></td>
        <td>${r.owner_name || "—"}</td>
        <td>${r.valid_from || "—"}</td>
        <td>${r.valid_until || "—"}</td>
      `;
      tbody.appendChild(tr);
    });
    $("stat-whitelist").textContent = rows.length;
  } catch { /* tabla vacía */ }
}

$("whitelist-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = {
    plate:       $("wl-plate").value.toUpperCase().trim(),
    owner_name:  $("wl-owner").value.trim(),
    valid_from:  $("wl-valid-from").value,
    valid_until: $("wl-valid-until").value,
  };
  try {
    const res = await fetch("/api/whitelist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      $("whitelist-form").reset();
      loadWhitelist();
    }
  } catch { /* silencioso */ }
});
