"use strict";

const $ = (s, el = document) => el.querySelector(s);

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = "";
    try { msg = (await res.json()).detail; } catch { /* corpo sem JSON */ }
    const err = new Error(msg || `Erro ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

const store = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem("pr:" + key);
      return v === null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("pr:" + key, JSON.stringify(value)); } catch { /* sem storage */ }
  },
};

const settings = {
  voice: store.get("voice", "natural"),
  rate: store.get("rate", 1),
  pause: store.get("pause", "paragraph"),
  repeat: store.get("repeat", 1),
  listen: store.get("listen", false),
};

let cfg = { extensions: [], voices: [], max_upload_mb: 10 };
let health = null;

/* ================================================================ rotas */

window.addEventListener("hashchange", route);

function route() {
  const m = location.hash.match(/^#\/doc\/([0-9a-f]{32})$/);
  if (m) openDoc(m[1]);
  else showHome();
}

/* ================================================================ biblioteca */

let libTimer = null;

function showHome() {
  closeReader();
  $("#home").hidden = false;
  document.title = "Personal Reader";
  loadLibrary();
}

async function loadLibrary() {
  clearTimeout(libTimer);
  let docs = [];
  try { docs = await api("/api/documents"); } catch { return; }
  const list = $("#lib-list");
  list.replaceChildren();
  $("#lib-empty").hidden = docs.length > 0;

  for (const doc of docs) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = `#/doc/${doc.id}`;
    const name = document.createElement("span");
    name.className = "doc-name";
    name.textContent = doc.name;
    const meta = document.createElement("span");
    meta.className = "doc-meta";
    a.append(name, meta);

    if (doc.status === "processing") {
      meta.textContent = "Convertendo o arquivo…";
    } else if (doc.status === "error") {
      meta.textContent = doc.error;
      meta.classList.add("bad");
    } else {
      const pos = store.get("pos:" + doc.id, 0);
      const pct = doc.segments ? Math.round((pos / doc.segments) * 100) : 0;
      meta.textContent = pos ? `${doc.segments} frases, ${pct}% ouvido` : `${doc.segments} frases`;
      const meter = document.createElement("span");
      meter.className = "meter";
      meter.innerHTML = `<span style="width:${pct}%"></span>`;
      if (pos) a.append(meter);
    }

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.textContent = "Apagar";
    remove.setAttribute("aria-label", `Apagar ${doc.name}`);
    remove.addEventListener("click", async () => {
      if (!confirm(`Apagar “${doc.name}” e o áudio gerado dele?`)) return;
      await api(`/api/documents/${doc.id}`, { method: "DELETE" }).catch(() => {});
      loadLibrary();
    });

    li.append(a, remove);
    list.append(li);
  }

  if (docs.some((d) => d.status === "processing")) libTimer = setTimeout(loadLibrary, 3000);
}

function setupUpload() {
  const drop = $("#drop");
  const input = $("#file-input");
  input.addEventListener("change", () => input.files[0] && upload(input.files[0]));
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]);
  });
}

async function upload(file) {
  const status = $("#upload-status");
  status.classList.remove("bad");
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!cfg.extensions.includes(ext)) {
    status.textContent = `${file.name}: formato não suportado. Use ${cfg.extensions.join(", ")}.`;
    status.classList.add("bad");
    return;
  }
  if (file.size > cfg.max_upload_mb * 1024 * 1024) {
    status.textContent = `${file.name} passa do limite de ${cfg.max_upload_mb} MB.`;
    status.classList.add("bad");
    return;
  }
  status.textContent = `Enviando ${file.name}…`;
  const form = new FormData();
  form.append("file", file);
  try {
    const doc = await api("/api/documents", { method: "POST", body: form });
    status.textContent = "";
    $("#file-input").value = "";
    location.hash = `#/doc/${doc.id}`;
  } catch (err) {
    status.textContent = `Não foi possível enviar ${file.name}: ${err.message}`;
    status.classList.add("bad");
  }
}

/* ================================================================ leitura */

const audio = new Audio();
audio.preload = "auto";

const R = {
  id: null,
  content: null,
  total: 0,
  index: 0,
  chunkStart: 0,
  chunkEnd: 0,
  unitEnd: [],
  playing: false,
  loading: false,
  atCheckpoint: false,
  loadedIndex: -1,
  repeatLeft: 0,
  heard: new Set(),
  spans: [],
  cache: new Map(), // "voz:índice" -> { promise, controller, url }
  bufferReady: [],
  pollTimer: null,
  prefetchTimer: null,
  loadTimer: null,
  openToken: 0,
};

function closeReader() {
  stopPlayback();
  clearTimeout(R.pollTimer);
  clearCache();
  R.id = null;
  $("#reader").hidden = true;
  $("#player").hidden = true;
}

async function openDoc(id) {
  closeReader();
  $("#home").hidden = true;
  $("#reader").hidden = false;
  $("#doc-text").replaceChildren();
  $("#doc-title").textContent = "";
  R.id = id;
  const token = ++R.openToken;

  let doc;
  try { doc = await api(`/api/documents/${id}`); } catch (err) {
    setDocState(err.status === 404 ? "Este texto não existe mais." : err.message, true);
    return;
  }
  if (token !== R.openToken) return;
  $("#doc-title").textContent = doc.name;
  document.title = `${doc.name} · Personal Reader`;

  if (doc.status === "processing") {
    setDocState("Convertendo o arquivo para texto. PDFs longos podem levar alguns minutos no servidor.");
    R.pollTimer = setTimeout(() => R.id === id && openDoc(id), 2500);
    return;
  }
  if (doc.status === "error") {
    setDocState(`A conversão falhou: ${doc.error}`, true);
    return;
  }
  setDocState("");
  R.content = doc.content;
  R.total = doc.content.segments.length;
  R.index = Math.min(store.get("pos:" + id, 0), R.total - 1);
  R.heard = new Set(Array.from({ length: R.index }, (_, i) => i));
  R.unitEnd = computeUnits(doc.content);
  renderText(doc.content);
  $("#player").hidden = false;
  selectSegment(R.index, { scroll: true });
  updatePlayer();
}

function setDocState(text, bad = false) {
  const el = $("#doc-state");
  el.textContent = text;
  el.classList.toggle("bad", bad);
}

/* Um "trecho" para as pausas de confirmação: título + parágrafo seguinte,
   ou uma lista inteira, contam como uma unidade só. */
function computeUnits(content) {
  const unitEnd = new Array(content.segments.length);
  const blocks = content.blocks.filter((b) => b.segments.length);
  let pending = [];
  blocks.forEach((b, n) => {
    pending.push(...b.segments);
    const next = blocks[n + 1];
    const joinNext = next && (b.type === "heading" || (b.type === "list" && next.type === "list"));
    if (!joinNext) {
      const last = pending[pending.length - 1];
      pending.forEach((i) => { unitEnd[i] = last; });
      pending = [];
    }
  });
  return unitEnd;
}

function chunkEndFor(start) {
  if (settings.pause === "paragraph") return R.unitEnd[start];
  return Math.min(start + Number(settings.pause) - 1, R.total - 1);
}

function renderText(content) {
  const root = $("#doc-text");
  root.replaceChildren();
  R.spans = [];
  let list = null;

  for (const block of content.blocks) {
    let el;
    if (block.type === "table") {
      el = document.createElement("div");
      el.className = "table";
      for (const row of block.rows) {
        const r = document.createElement("div");
        r.textContent = row;
        el.append(r);
      }
      root.append(el);
      list = null;
      continue;
    }
    if (block.type === "list") {
      if (!list) { list = document.createElement("ul"); root.append(list); }
      el = document.createElement("li");
      list.append(el);
    } else {
      list = null;
      if (block.type === "heading") el = document.createElement(`h${Math.min(Math.max(block.level, 2), 4)}`);
      else if (block.type === "quote") el = document.createElement("blockquote");
      else el = document.createElement("p");
      root.append(el);
    }
    block.segments.forEach((i, n) => {
      const span = document.createElement("span");
      span.className = "s";
      span.dataset.i = i;
      span.textContent = content.segments[i].text;
      el.append(span);
      if (n < block.segments.length - 1) el.append(" ");
      R.spans[i] = span;
    });
  }
  refreshVeil();
}

function refreshVeil() {
  R.spans.forEach((span, i) => span.classList.toggle("veiled", settings.listen && !R.heard.has(i)));
}

function selectSegment(i, { scroll = false } = {}) {
  R.spans[R.index]?.classList.remove("current");
  R.index = i;
  const span = R.spans[i];
  span?.classList.add("current");
  if (span && scroll) {
    const rect = span.getBoundingClientRect();
    const limit = window.innerHeight - $("#player").offsetHeight - 40;
    if (rect.top < 80 || rect.bottom > limit) {
      span.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }
  store.set("pos:" + R.id, i);
  updatePlayer();
}

function markHeard(i) {
  R.heard.add(i);
  R.spans[i]?.classList.add("heard");
  R.spans[i]?.classList.remove("veiled");
}

/* ---------------------------------------------------------------- áudio */

function cacheKey(i) { return `${settings.voice}:${i}`; }

function getAudio(i) {
  const key = cacheKey(i);
  let entry = R.cache.get(key);
  if (entry) return entry.promise;
  const controller = new AbortController();
  const url = `/api/documents/${R.id}/segments/${i}/audio?voice=${encodeURIComponent(settings.voice)}`;
  entry = { controller, url: null };
  entry.promise = fetch(url, { signal: controller.signal }).then(async (res) => {
    if (!res.ok) {
      let msg = "";
      try { msg = (await res.json()).detail; } catch { /* sem JSON */ }
      throw new Error(msg || `Erro ${res.status}`);
    }
    entry.url = URL.createObjectURL(await res.blob());
    return entry.url;
  });
  entry.promise.catch(() => R.cache.delete(key));
  R.cache.set(key, entry);
  trimCache();
  return entry.promise;
}

function trimCache() {
  for (const [key, entry] of R.cache) {
    const i = Number(key.split(":").pop());
    if (i < R.index - 3 || i > R.chunkEnd + 3 || !key.startsWith(settings.voice + ":")) {
      if (entry.url) URL.revokeObjectURL(entry.url);
      else entry.controller.abort();
      R.cache.delete(key);
    }
  }
}

function clearCache() {
  for (const entry of R.cache.values()) {
    if (entry.url) URL.revokeObjectURL(entry.url);
    else entry.controller.abort();
  }
  R.cache.clear();
}

function stopPlayback() {
  R.playing = false;
  R.atCheckpoint = false;
  setLoading(false);
  audio.pause();
  clearTimeout(R.prefetchTimer);
  removeCheckpoint();
}

function playFrom(i, { newChunk = true } = {}) {
  removeCheckpoint();
  R.atCheckpoint = false;
  if (newChunk) {
    R.chunkStart = i;
    R.chunkEnd = chunkEndFor(i);
  }
  R.repeatLeft = Number(settings.repeat) - 1;
  R.playing = true;
  selectSegment(i, { scroll: true });
  trimCache();
  playCurrent();
}

async function playCurrent() {
  const i = R.index;
  requestPrefetch();
  setLoading(true);
  let url;
  try {
    url = await getAudio(i);
  } catch (err) {
    if (err.name === "AbortError" || i !== R.index) return;
    setLoading(false);
    R.playing = false;
    setPlayState(`Não foi possível gerar esta frase: ${err.message}`);
    updatePlayer();
    return;
  }
  if (i !== R.index || !R.playing) { setLoading(false); return; }

  audio.src = url;
  audio.playbackRate = Number(settings.rate);
  audio.preservesPitch = true;
  R.loadedIndex = i;
  try {
    await audio.play();
  } catch {
    // Navegador bloqueou o autoplay; espera o próximo clique em tocar.
    R.playing = false;
  }
  setLoading(false);
  updatePlayer();

  // A próxima frase pede prioridade máxima no servidor enquanto esta toca.
  const next = i + 1;
  if (next < R.total && next <= R.chunkEnd + 1) getAudio(next).catch(() => {});
}

audio.addEventListener("ended", () => {
  if (!R.playing) return;
  if (R.repeatLeft > 0) {
    R.repeatLeft -= 1;
    setTimeout(() => {
      if (!R.playing) return;
      audio.currentTime = 0;
      audio.play().catch(() => {});
    }, 700);
    return;
  }
  markHeard(R.index);
  if (R.index >= R.total - 1) {
    stopPlayback();
    setPlayState("Fim do texto.");
    updatePlayer();
    return;
  }
  if (R.index >= R.chunkEnd) {
    showCheckpoint();
    return;
  }
  R.repeatLeft = Number(settings.repeat) - 1;
  const next = R.index + 1;
  selectSegment(next, { scroll: true });
  setTimeout(() => R.playing && R.index === next && playCurrent(), 250);
});

audio.addEventListener("error", () => {
  if (!R.playing) return;
  R.playing = false;
  setPlayState("O navegador não conseguiu tocar este áudio.");
  updatePlayer();
});

/* ---------------------------------------------------------------- pausas de confirmação */

function showCheckpoint() {
  R.playing = false;
  R.atCheckpoint = true;
  clearTimeout(R.prefetchTimer);
  const span = R.spans[R.index];
  const anchor = span.closest("ul, p, blockquote, h2, h3, h4");
  const node = $("#checkpoint-tpl").content.firstElementChild.cloneNode(true);
  node.id = "checkpoint";
  node.addEventListener("click", (e) => {
    const act = e.target.closest("button")?.dataset.act;
    if (act === "continue") continueReading();
    if (act === "replay") replayChunk();
  });
  anchor.after(node);
  $("button.primary", node).focus({ preventScroll: true });
  node.scrollIntoView({ block: "nearest", behavior: "smooth" });
  setPlayState("Pausado para você confirmar.");
  updatePlayer();
  if ("vibrate" in navigator) navigator.vibrate?.(60);
}

function removeCheckpoint() {
  $("#checkpoint")?.remove();
}

function continueReading() {
  if (R.index + 1 < R.total) playFrom(R.index + 1);
}

function replayChunk() {
  for (let i = R.chunkStart; i <= R.chunkEnd; i++) {
    R.heard.delete(i);
    R.spans[i].classList.remove("heard");
  }
  refreshVeil();
  playFrom(R.chunkStart, { newChunk: false });
}

/* ---------------------------------------------------------------- pré-carga */

async function requestPrefetch() {
  clearTimeout(R.prefetchTimer);
  if (!R.id || !R.content) return;
  const start = R.index;
  const end = Math.min(R.chunkEnd + 2, R.total);
  try {
    const res = await api(`/api/documents/${R.id}/prefetch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice: settings.voice, start, end }),
    });
    R.bufferReady = res.ready.map((ok, n) => (ok ? res.start + n : -1)).filter((x) => x >= 0);
  } catch { /* o indicador só fica desatualizado */ }
  renderBuffer();
  if (R.playing || R.loading) R.prefetchTimer = setTimeout(requestPrefetch, 3000);
}

function renderBuffer() {
  const box = $("#buffer");
  box.replaceChildren();
  const from = R.chunkStart;
  const to = Math.min(R.chunkEnd, from + 14);
  if (!R.playing && !R.loading && !R.atCheckpoint) return;
  for (let i = from; i <= to; i++) {
    const tick = document.createElement("i");
    if (i === R.index) tick.className = "now";
    else if (R.heard.has(i) || R.bufferReady.includes(i) || R.cache.get(cacheKey(i))?.url) tick.className = "ready";
    box.append(tick);
  }
}

/* ---------------------------------------------------------------- estado do player */

function setLoading(on) {
  R.loading = on;
  clearInterval(R.loadTimer);
  $("#player").classList.toggle("loading", on);
  if (on) {
    const started = Date.now();
    const tick = () => {
      const s = Math.round((Date.now() - started) / 1000);
      setPlayState(s < 2 ? "Gerando a voz desta frase…" : `Gerando a voz desta frase… ${s} s`);
    };
    tick();
    R.loadTimer = setInterval(tick, 1000);
  } else {
    setPlayState("");
  }
}

function setPlayState(text) {
  $("#play-state").textContent = text;
}

function updatePlayer() {
  const player = $("#player");
  player.classList.toggle("playing", R.playing && !R.loading);
  $("#btn-play").setAttribute("aria-label", R.playing ? "Pausar" : R.atCheckpoint ? "Continuar leitura" : "Tocar");
  $("#position").textContent = R.total ? `Frase ${R.index + 1} de ${R.total}` : "—";
  $("#btn-prev").disabled = R.index <= 0;
  $("#btn-next").disabled = R.index >= R.total - 1;
  renderBuffer();
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = R.playing ? "playing" : "paused";
}

function togglePlay() {
  if (!R.total) return;
  if (R.atCheckpoint) return continueReading();
  if (R.playing) {
    R.playing = false;
    audio.pause();
    clearTimeout(R.prefetchTimer);
    setLoading(false);
    updatePlayer();
    return;
  }
  if (R.loadedIndex === R.index && audio.src && audio.currentTime > 0 && !audio.ended) {
    R.playing = true;
    audio.play().catch(() => {});
    requestPrefetch();
    updatePlayer();
    return;
  }
  playFrom(R.index);
}

function step(delta) {
  const i = Math.min(Math.max(R.index + delta, 0), R.total - 1);
  if (i === R.index) return;
  if (R.playing || R.loading) {
    playFrom(i);
  } else {
    removeCheckpoint();
    R.atCheckpoint = false;
    audio.pause();
    R.loadedIndex = -1;
    selectSegment(i, { scroll: true });
  }
}

function playAgain() {
  if (R.loadedIndex === R.index && audio.src) {
    removeCheckpoint();
    R.atCheckpoint = false;
    R.playing = true;
    R.repeatLeft = 0;
    audio.currentTime = 0;
    audio.play().catch(() => {});
    updatePlayer();
  } else {
    playFrom(R.index, { newChunk: !R.chunkEnd || R.index > R.chunkEnd || R.index < R.chunkStart });
  }
}

function reveal() {
  markHeard(R.index);
}

/* ================================================================ ajustes */

function setupSettings() {
  const voice = $("#opt-voice");
  // Vozes com grupo (idioma) viram <optgroup>; a ordem vem do servidor.
  const groups = new Map();
  for (const v of cfg.voices) {
    if (!groups.has(v.group)) groups.set(v.group, []);
    groups.get(v.group).push(new Option(v.label, v.id));
  }
  voice.replaceChildren(...[...groups].flatMap(([group, options]) => {
    if (!group) return options;
    const og = document.createElement("optgroup");
    og.label = group;
    og.append(...options);
    return [og];
  }));
  $("#voice-hint").hidden = groups.size < 2;
  if (!cfg.voices.some((v) => v.id === settings.voice)) settings.voice = cfg.voices[0]?.id || "natural";
  voice.value = settings.voice;
  $("#opt-rate").value = String(settings.rate);
  $("#opt-pause").value = String(settings.pause);
  $("#opt-repeat").value = String(settings.repeat);
  $("#opt-listen").checked = settings.listen;

  voice.addEventListener("change", () => {
    settings.voice = voice.value;
    store.set("voice", settings.voice);
    clearCache();
    R.loadedIndex = -1;
    if (R.playing || R.loading) playFrom(R.index, { newChunk: false });
  });
  $("#opt-rate").addEventListener("change", (e) => {
    settings.rate = Number(e.target.value);
    store.set("rate", settings.rate);
    audio.playbackRate = settings.rate;
  });
  $("#opt-pause").addEventListener("change", (e) => {
    settings.pause = e.target.value;
    store.set("pause", settings.pause);
    if (R.total) R.chunkEnd = Math.max(chunkEndFor(R.chunkStart), R.index);
    renderBuffer();
  });
  $("#opt-repeat").addEventListener("change", (e) => {
    settings.repeat = Number(e.target.value);
    store.set("repeat", settings.repeat);
  });
  $("#opt-listen").addEventListener("change", (e) => {
    settings.listen = e.target.checked;
    store.set("listen", settings.listen);
    refreshVeil();
  });

  $("#btn-settings").addEventListener("click", (e) => {
    const panel = $("#settings");
    panel.hidden = !panel.hidden;
    e.currentTarget.setAttribute("aria-expanded", String(!panel.hidden));
  });
}

/* ================================================================ status do motor */

async function pollHealth() {
  const el = $("#engine-status");
  try {
    health = await api("/api/health");
    el.classList.toggle("bad", Boolean(health.error));
    if (health.error) el.textContent = "Voz indisponível no servidor";
    else if (!health.ready) el.textContent = "Carregando o modelo de voz…";
    else if (health.rtf) el.textContent = `Cada segundo de fala leva ~${health.rtf.toLocaleString("pt-BR")} s para gerar`;
    else el.textContent = "Voz pronta";
    el.title = health.error || "";
  } catch {
    el.textContent = "Servidor fora do ar";
    el.classList.add("bad");
  }
  setTimeout(pollHealth, health && !health.ready && !health.error ? 3000 : 15000);
}

/* ================================================================ entrada */

function setupControls() {
  $("#btn-play").addEventListener("click", togglePlay);
  $("#btn-prev").addEventListener("click", () => step(-1));
  $("#btn-next").addEventListener("click", () => step(1));
  $("#btn-again").addEventListener("click", playAgain);
  $("#doc-text").addEventListener("click", (e) => {
    const span = e.target.closest(".s");
    if (span && !window.getSelection().toString()) playFrom(Number(span.dataset.i));
  });

  document.addEventListener("keydown", (e) => {
    if ($("#reader").hidden || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest("input, select, textarea")) return;
    const onButton = e.target.closest("button");
    if (e.key === " " && !onButton) { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "a" || e.key === "A") playAgain();
    else if (e.key === "r" || e.key === "R") reveal();
  });

  if ("mediaSession" in navigator) {
    const ms = navigator.mediaSession;
    ms.setActionHandler("play", togglePlay);
    ms.setActionHandler("pause", togglePlay);
    ms.setActionHandler("previoustrack", () => step(-1));
    ms.setActionHandler("nexttrack", () => step(1));
  }
}

async function init() {
  try { cfg = await api("/api/config"); } catch { /* segue com o padrão */ }
  $("#formats").textContent = `Aceita ${cfg.extensions.join(", ")}, até ${cfg.max_upload_mb} MB.`;
  setupUpload();
  setupSettings();
  setupControls();
  pollHealth();
  route();
}

init();
