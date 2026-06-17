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
  loadPayments();
  startCameraPolling();
  loadWhitelistStats();
  if (role === "admin") loadWhitelist();
}

$("logout-btn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  location.reload();
});

// ── Socket.IO ──────────────────────────────────────────────────────────────

function connectSocket() {
  // socket.io se carga de un CDN; si no hay internet, no rompemos el resto del
  // dashboard (cámara y eventos siguen funcionando por polling REST).
  if (typeof io === "undefined") {
    $("mqtt-status").className = "status-dot offline";
    $("mqtt-status").title = "socket.io no disponible (sin tiempo real)";
    return;
  }
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

  // Pago registrado → refrescar tabla de pagos desde la BD (fuente de verdad).
  if (topic.includes("/events/payment")) {
    loadPayments();
  }

  // Nuevo vehículo o decisión → la cámara acaba de capturar evidencia: refrescar pronto.
  if (topic.includes("presence_detected") ||
      topic.includes("access_granted") || topic.includes("access_denied")) {
    setTimeout(loadCaptures, 1500);
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

// ── Pagos ────────────────────────────────────────────────────────────────────

function moneyCOP(n) {
  return n != null ? "$" + Number(n).toLocaleString("es-CO") : "—";
}

function paymentStatusClass(status) {
  const s = (status || "").toUpperCase();
  if (s === "APPROVED" || s === "OK" || s === "DUPLICATE") return "pay-approved";
  if (s === "FAILED")  return "pay-failed";
  return "pay-pending";  // PENDING, QUEUED, etc.
}

function isApproved(status) {
  const s = (status || "").toUpperCase();
  return s === "APPROVED" || s === "OK" || s === "DUPLICATE";
}

async function loadPayments() {
  try {
    const res = await fetch("/api/payments?limit=50");
    if (!res.ok) return;
    const rows = await res.json();
    const tbody = $("payments-body");
    tbody.innerHTML = "";
    let approved = 0;
    rows.forEach(p => {
      tbody.appendChild(buildPaymentRow(p));
      if (isApproved(p.status)) approved++;
    });
    $("payment-count").textContent  = rows.length;
    $("stat-payments").textContent  = approved;
  } catch { /* tabla vacía */ }
}

function buildPaymentRow(p) {
  const tr = document.createElement("tr");
  const cls = paymentStatusClass(p.status);
  tr.innerHTML = `
    <td>${formatTime(p.created_at)}</td>
    <td><strong>${p.plate || "—"}</strong></td>
    <td>${moneyCOP(p.amount_cop)}</td>
    <td class="${cls}">${(p.status || "—").toUpperCase()}</td>
  `;
  return tr;
}

// ── Cámara: vista en vivo (latest.jpg) + galería de evidencia ────────────────
// El vision-service reescribe latest.jpg en cada frame mientras hay un vehículo.
// Refrescamos esa imagen rápido para dar sensación de vídeo en vivo, y dejamos
// la galería (capturas con timestamp) como historial de lo detectado.

let _liveTimer    = null;
let _galleryTimer = null;
const LIVE_REFRESH_MS = 500;

function startCameraPolling() {
  refreshLive();
  loadCaptures();
  if (_liveTimer)    clearInterval(_liveTimer);
  if (_galleryTimer) clearInterval(_galleryTimer);
  _liveTimer    = setInterval(refreshLive, LIVE_REFRESH_MS);
  _galleryTimer = setInterval(loadCaptures, 3000);
}

function refreshLive() {
  const img   = $("camera-latest");
  const empty = $("camera-empty");
  // onload/onerror controlan el estado vacío sin pegarle a otro endpoint.
  img.onload  = () => { empty.classList.add("hidden");    img.classList.remove("hidden"); };
  img.onerror = () => { img.classList.add("hidden"); empty.classList.remove("hidden"); };
  img.src = `/api/captures/latest.jpg?t=${Date.now()}`;
}

function captureUrl(item) {
  return `/api/captures/${encodeURIComponent(item.file)}?t=${Math.floor(item.mtime)}`;
}

async function loadCaptures() {
  try {
    const res = await fetch("/api/captures?limit=12");
    if (!res.ok) return;
    const items = await res.json();
    if (!Array.isArray(items)) return;

    const gal = $("camera-gallery");
    gal.innerHTML = "";
    // Historial: clic abre la captura en otra pestaña (no pisa la vista en vivo).
    items.forEach(it => {
      const thumb = document.createElement("img");
      thumb.className = "camera-thumb";
      thumb.src = captureUrl(it);
      thumb.title = new Date(it.mtime * 1000).toLocaleString("es-CO");
      thumb.addEventListener("click", () => window.open(captureUrl(it), "_blank"));
      gal.appendChild(thumb);
    });

    $("capture-count").textContent = items.length;
  } catch { /* sin capturas */ }
}

// ── Whitelist ────────────────────────────────────────────────────────────────

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
