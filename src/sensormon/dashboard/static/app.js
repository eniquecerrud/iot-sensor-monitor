const state = {
  catalog: [],
  catalogById: {},
  devices: [],
  alerts: [],
  series: {},
  selected: null,
  ws: null,
};

const severityLabel = {
  info: "info",
  warning: "aviso",
  critical: "crítica",
};

const devicesEl = document.querySelector("#devices");
const alertsEl = document.querySelector("#alerts");
const kpisEl = document.querySelector("#kpis");
const chartsEl = document.querySelector("#charts");
const statusEl = document.querySelector("#status");
const countEl = document.querySelector("#alert-count");
const clockEl = document.querySelector("#clock");
const nameEl = document.querySelector("#device-name");
const locationEl = document.querySelector("#device-location");

devicesEl.addEventListener("click", (event) => {
  const button = event.target.closest("[data-device]");
  if (!button) return;
  selectDevice(button.dataset.device);
});

function spec(id) {
  return state.catalogById[id] || { id, label: id, unit: "", color: "#d9c7a6" };
}

function seriesKey(deviceId, metric) {
  return `${deviceId}|${metric}`;
}

function formatValue(metric, value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const digits = metric === "co2" ? 0 : metric === "pressure" ? 1 : 2;
  return value.toLocaleString("es-ES", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatClock(date) {
  return date.toLocaleTimeString("es-ES", { hour12: false });
}

function ago(iso) {
  if (!iso) return "sin datos";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 5) return "ahora";
  if (seconds < 60) return `hace ${Math.floor(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  return new Date(iso).toLocaleString("es-ES");
}

function setStatus(mode, label) {
  statusEl.textContent = label;
  statusEl.className = `status is-${mode}`;
}

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

function pointFrom(reading) {
  return { t: reading.timestamp, v: reading.value };
}

function pushPoint(reading) {
  const key = seriesKey(reading.device_id, reading.metric);
  const series = state.series[key] || (state.series[key] = []);
  const point = pointFrom(reading);
  const existing = series.findIndex((item) => item.t === point.t);
  if (existing >= 0) series[existing] = point;
  else series.push(point);
  if (series.length > 90) series.shift();
}

function emptyNode(text) {
  const node = document.createElement("div");
  node.className = "empty";
  node.textContent = text;
  return node;
}

function renderDevices() {
  devicesEl.replaceChildren();
  if (!state.devices.length) {
    devicesEl.append(emptyNode("Todavía no hay dispositivos."));
    return;
  }
  for (const device of state.devices) {
    const button = document.createElement("button");
    button.className = "device";
    button.dataset.device = device.device_id;
    if (device.device_id === state.selected) button.classList.add("is-active");

    const dot = document.createElement("span");
    const age = device.last_seen ? (Date.now() - new Date(device.last_seen).getTime()) / 1000 : 999;
    dot.className = `dot ${age < 15 ? "is-ok" : "is-stale"}`;

    const text = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = device.device_id;
    const meta = document.createElement("small");
    meta.textContent = `${device.location || "Sin ubicación"} · ${ago(device.last_seen)}`;
    text.append(title, meta);
    button.append(dot, text);
    devicesEl.append(button);
  }
}

function renderSummary() {
  const device = state.devices.find((item) => item.device_id === state.selected);
  nameEl.textContent = device ? device.device_id : "Sin dispositivo";
  locationEl.textContent = device
    ? device.location || "Ubicación no anunciada"
    : "Arranca el simulador o abre el modo embebido";
}

function renderKpis() {
  const device = state.devices.find((item) => item.device_id === state.selected);
  kpisEl.replaceChildren();
  if (!device) return;
  const metrics = device.sensors.length ? device.sensors : Object.keys(device.latest || {});
  if (!metrics.length) {
    kpisEl.append(emptyNode("Este dispositivo aún no ha publicado lecturas."));
    return;
  }
  for (const metric of metrics) {
    const latest = device.latest ? device.latest[metric] : null;
    const card = document.createElement("article");
    card.className = "kpi";
    if (latest && latest.quality && latest.quality !== "good") card.classList.add(`is-${latest.quality}`);
    const label = document.createElement("span");
    label.textContent = spec(metric).label;
    const value = document.createElement("strong");
    value.textContent = latest ? formatValue(metric, latest.value) : "—";
    const unit = document.createElement("em");
    unit.textContent = latest ? ` ${latest.unit}` : "";
    value.append(unit);
    card.append(label, value);
    kpisEl.append(card);
  }
}

function renderCharts() {
  const device = state.devices.find((item) => item.device_id === state.selected);
  chartsEl.replaceChildren();
  if (!device) return;
  const metrics = device.sensors.length ? device.sensors : Object.keys(device.latest || {});
  for (const metric of metrics) {
    const card = document.createElement("article");
    card.className = "chart-card";
    const header = document.createElement("header");
    const swatch = document.createElement("i");
    swatch.className = "swatch";
    swatch.style.background = spec(metric).color;
    const title = document.createElement("strong");
    title.textContent = spec(metric).label;
    const latest = device.latest ? device.latest[metric] : null;
    const value = document.createElement("em");
    value.textContent = latest ? `${formatValue(metric, latest.value)} ${latest.unit}` : "sin datos";
    header.append(swatch, title, value);
    const canvas = document.createElement("canvas");
    canvas.dataset.metric = metric;
    card.append(header, canvas);
    chartsEl.append(card);
  }
  requestAnimationFrame(drawAll);
}

function renderAlerts() {
  alertsEl.replaceChildren();
  countEl.textContent = String(state.alerts.length);
  if (!state.alerts.length) {
    alertsEl.append(emptyNode("Sin alertas. Los detectores publicarán aquí los eventos."));
    return;
  }
  for (const alert of state.alerts) {
    const card = document.createElement("article");
    card.className = `alert is-${alert.severity}`;
    const header = document.createElement("header");
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = severityLabel[alert.severity] || alert.severity;
    const time = document.createElement("time");
    time.dateTime = alert.timestamp;
    time.textContent = formatClock(new Date(alert.timestamp));
    header.append(badge, time);
    const message = document.createElement("p");
    message.textContent = alert.message;
    const footer = document.createElement("footer");
    footer.textContent = `${alert.device_id} · ${alert.detector} · ${formatValue(alert.metric, alert.value)} ${spec(alert.metric).unit}`;
    card.append(header, message, footer);
    alertsEl.append(card);
  }
}

function drawAll() {
  for (const canvas of chartsEl.querySelectorAll("canvas")) {
    const metric = canvas.dataset.metric;
    const series = state.series[seriesKey(state.selected, metric)] || [];
    drawChart(canvas, series, spec(metric).color);
  }
}

function drawChart(canvas, points, color) {
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width < 20 || height < 20) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const left = 46;
  const right = 10;
  const top = 12;
  const bottom = 18;
  const innerW = width - left - right;
  const innerH = height - top - bottom;

  if (points.length === 0) {
    ctx.fillStyle = "#a39886";
    ctx.font = "13px sans-serif";
    ctx.fillText("Esperando datos…", left, height / 2);
    return;
  }

  const values = points.map((point) => point.v);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.14;
  min -= pad;
  max += pad;

  ctx.strokeStyle = "rgba(243, 239, 230, 0.08)";
  ctx.fillStyle = "#a39886";
  ctx.font = "11px ui-monospace, monospace";
  ctx.lineWidth = 1;
  ctx.textAlign = "right";
  for (let i = 0; i < 4; i += 1) {
    const y = top + (innerH * i) / 3;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
    const label = max - ((max - min) * i) / 3;
    ctx.fillText(label.toFixed(Math.abs(label) >= 100 ? 0 : 1), left - 6, y + 4);
  }

  const coords = points.map((point, index) => {
    const x = left + (points.length === 1 ? innerW / 2 : (innerW * index) / (points.length - 1));
    const y = top + innerH * (1 - (point.v - min) / (max - min));
    return [x, y];
  });

  ctx.beginPath();
  coords.forEach(([x, y], index) => {
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.lineTo(coords[coords.length - 1][0], top + innerH);
  ctx.lineTo(coords[0][0], top + innerH);
  ctx.closePath();
  ctx.fillStyle = hexToRgba(color, 0.16);
  ctx.fill();
}

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const number = Number.parseInt(value, 16);
  const r = (number >> 16) & 255;
  const g = (number >> 8) & 255;
  const b = number & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function upsertDevice(reading) {
  let device = state.devices.find((item) => item.device_id === reading.device_id);
  if (!device) {
    device = {
      device_id: reading.device_id,
      location: null,
      last_seen: reading.timestamp,
      sensors: [reading.metric],
      reading_count: 1,
      latest: {},
    };
    state.devices.push(device);
    state.devices.sort((a, b) => a.device_id.localeCompare(b.device_id));
  }
  device.last_seen = reading.timestamp;
  device.reading_count = (device.reading_count || 0) + 1;
  if (!device.sensors.includes(reading.metric)) device.sensors.push(reading.metric);
  device.latest = device.latest || {};
  device.latest[reading.metric] = reading;
  if (!state.selected) state.selected = device.device_id;
}

function ingestReading(reading) {
  const known = state.devices.some((item) => item.device_id === reading.device_id);
  upsertDevice(reading);
  pushPoint(reading);
  if (!known) {
    renderDevices();
    renderSummary();
    renderKpis();
    renderCharts();
    return;
  }
  renderDevices();
  if (reading.device_id === state.selected) {
    renderKpis();
    renderCharts();
  }
}

function ingestAlert(alert) {
  if (state.alerts.some((item) => item.id && item.id === alert.id)) return;
  state.alerts.unshift(alert);
  state.alerts = state.alerts.slice(0, 50);
  renderAlerts();
}

async function loadSeries(deviceId) {
  const device = state.devices.find((item) => item.device_id === deviceId);
  const metrics = device && device.sensors.length ? device.sensors : state.catalog.map((item) => item.id);
  await Promise.all(
    metrics.map(async (metric) => {
      const rows = await fetchJSON(
        `/api/readings?device_id=${encodeURIComponent(deviceId)}&metric=${encodeURIComponent(metric)}&limit=90`,
      );
      state.series[seriesKey(deviceId, metric)] = rows.map(pointFrom);
    }),
  );
}

async function selectDevice(deviceId) {
  state.selected = deviceId;
  renderDevices();
  renderSummary();
  try {
    await loadSeries(deviceId);
  } catch (error) {
    console.error(error);
  }
  renderKpis();
  renderCharts();
}

async function refreshAll() {
  const [devices, alerts] = await Promise.all([
    fetchJSON("/api/devices"),
    fetchJSON("/api/alerts?limit=50"),
  ]);
  state.devices = devices;
  state.alerts = alerts;
  if (!state.selected && devices.length) state.selected = devices[0].device_id;
  if (state.selected && !devices.some((item) => item.device_id === state.selected)) {
    state.selected = devices[0] ? devices[0].device_id : null;
  }
  renderDevices();
  renderSummary();
  renderAlerts();
  if (state.selected) await loadSeries(state.selected);
  renderKpis();
  renderCharts();
}

let wsOpen = false;

async function poll() {
  try {
    const [devices, alerts] = await Promise.all([
      fetchJSON("/api/devices"),
      fetchJSON("/api/alerts?limit=50"),
    ]);
    state.devices = devices;
    state.alerts = alerts;
    if (!state.selected && devices.length) state.selected = devices[0].device_id;
    if (state.selected) {
      const device = devices.find((item) => item.device_id === state.selected);
      const metrics = device && device.sensors.length ? device.sensors : [];
      await Promise.all(
        metrics.map(async (metric) => {
          const rows = await fetchJSON(
            `/api/readings?device_id=${encodeURIComponent(state.selected)}&metric=${encodeURIComponent(metric)}&limit=90`,
          );
          state.series[seriesKey(state.selected, metric)] = rows.map(pointFrom);
        }),
      );
    }
    renderDevices();
    renderSummary();
    renderAlerts();
    renderKpis();
    renderCharts();
    if (!wsOpen) setStatus("live", "en vivo");
  } catch (error) {
    console.error(error);
    if (!wsOpen) setStatus("down", "sin api");
  }
}

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  state.ws = ws;
  setStatus("wait", "conectando");
  ws.onopen = () => {
    wsOpen = true;
    setStatus("live", "en vivo");
  };
  ws.onclose = () => {
    wsOpen = false;
    setStatus("down", "reconectando");
    setTimeout(connectWS, 1200);
  };
  ws.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      console.error(error);
      return;
    }
    if (message.type === "snapshot") {
      if (Array.isArray(message.devices) && message.devices.length) state.devices = message.devices;
      if (Array.isArray(message.alerts)) state.alerts = message.alerts;
      if (!state.selected && state.devices.length) state.selected = state.devices[0].device_id;
      renderDevices();
      renderSummary();
      renderAlerts();
      renderKpis();
    } else if (message.type === "reading") {
      ingestReading(message.data);
    } else if (message.type === "alert") {
      ingestAlert(message.data);
    }
  };
}

async function boot() {
  try {
    state.catalog = await fetchJSON("/api/catalog");
    state.catalogById = Object.fromEntries(state.catalog.map((item) => [item.id, item]));
    await refreshAll();
    setStatus("wait", "histórico listo");
  } catch (error) {
    console.error(error);
    setStatus("down", "sin api");
    devicesEl.append(emptyNode("No se pudo cargar el API."));
  }
  connectWS();
  window.setInterval(poll, 2000);
}

window.setInterval(() => {
  clockEl.textContent = formatClock(new Date());
  renderDevices();
}, 1000);
clockEl.textContent = formatClock(new Date());

const observer = new ResizeObserver(() => drawAll());
observer.observe(chartsEl);
window.addEventListener("resize", drawAll);
boot();
