'use strict';

const $ = (id) => document.getElementById(id);
const els = {
  model: $('model'), source: $('source'), hint: $('source-hint'), note: $('support-note'),
  title: $('title'), glossary: $('glossary'), toggle: $('toggle'), status: $('status'),
  timer: $('timer'), level: $('level'), banner: $('banner'), log: $('log'),
  current: $('current'), copy: $('copy'), openFolder: $('open-folder'),
};

const HINTS = {
  mic: '',
  tab: 'Nel selettore scegli una scheda e spunta «Condividi anche l\'audio della scheda» ' +
       '(su Windows puoi condividere anche lo schermo intero con l\'audio di sistema).',
  both: 'Nel selettore scegli una scheda e spunta «Condividi anche l\'audio della scheda» ' +
        '(su Windows puoi condividere anche lo schermo intero con l\'audio di sistema). ' +
        'Usa le cuffie, altrimenti il microfono riprende l\'audio della lezione.',
};

let ws = null;
let audioCtx = null;
let streams = [];
let sending = false;
let running = false;
let stopping = false;
let finished = false;
let wakeLock = null;
let timerId = null;
let t0 = 0;
let paras = [];
let curr = null;
let statusText = 'Pronto';
let statusBusy = false;
let dots = 0;
let savedMd = '';

// ---------- helpers ----------

function hms(sec) {
  const s = Math.floor(Math.max(0, sec));
  const p = (n) => String(n).padStart(2, '0');
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

function setStatus(text, busy = false) {
  statusText = text;
  statusBusy = busy;
  renderStatus();
}

function renderStatus() {
  els.status.textContent = statusText + (statusBusy ? '.'.repeat(dots % 4) : '');
}
setInterval(() => { if (statusBusy) { dots++; renderStatus(); } }, 400);

function atBottom() {
  return els.log.scrollHeight - els.log.scrollTop - els.log.clientHeight < 40;
}

function addParagraph(start, text) {
  const stick = atBottom();
  paras.push({ start, text });
  const div = document.createElement('p');
  div.className = 'par';
  const b = document.createElement('b');
  b.textContent = `[${hms(start)}]`;
  div.append(b, document.createTextNode(text));
  els.log.insertBefore(div, els.current);
  if (stick) els.log.scrollTop = els.log.scrollHeight;
}

function setCurrent(start, text) {
  const stick = atBottom();
  curr = text ? { start, text } : null;
  els.current.textContent = text ? `[${hms(start)}] ${text}` : '';
  if (stick) els.log.scrollTop = els.log.scrollHeight;
}

function clearLog() {
  paras = [];
  curr = null;
  els.log.querySelectorAll('.par').forEach((n) => n.remove());
  els.current.textContent = '';
}

function startTimer() {
  t0 = Date.now();
  clearInterval(timerId);
  timerId = setInterval(() => { els.timer.textContent = hms((Date.now() - t0) / 1000); }, 500);
}

function stopTimer() {
  clearInterval(timerId);
  timerId = null;
}

// ---------- support checks ----------

const hasUserMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
const hasDisplayAudio = !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia &&
                           typeof AudioWorkletNode !== 'undefined');

function updateHint() {
  els.hint.textContent = HINTS[els.source.value] || '';
}

function checkSupport() {
  if (!hasDisplayAudio) {
    for (const o of els.source.options) if (o.value !== 'mic') o.disabled = true;
    els.note.classList.remove('hidden');
  }
  if (!hasUserMedia || typeof AudioWorkletNode === 'undefined') {
    els.toggle.disabled = true;
    setStatus('Errore: il browser non supporta la cattura audio');
  }
  updateHint();
}

els.source.addEventListener('change', updateHint);

// ---------- audio ----------

function releaseAudio() {
  sending = false;
  for (const s of streams) s.getTracks().forEach((t) => t.stop());
  streams = [];
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  if (wakeLock) { wakeLock.release().catch(() => {}); wakeLock = null; }
  window.removeEventListener('beforeunload', onBeforeUnload);
  els.level.style.width = '0';
}

function onBeforeUnload(e) {
  e.preventDefault();
  e.returnValue = '';
}

function resetControls() {
  running = false;
  stopping = false;
  els.toggle.textContent = 'Avvia';
  els.toggle.disabled = false;
  els.source.disabled = false;
  els.model.disabled = false;
  els.title.disabled = false;
  els.glossary.disabled = false;
  stopTimer();
}

function fail(text) {
  releaseAudio();
  if (ws) { try { ws.close(); } catch (e) { /* ignore */ } }
  ws = null;
  resetControls();
  setStatus(text);
}

async function start() {
  const source = els.source.value;
  const wantMic = source === 'mic' || source === 'both';
  const wantTab = source === 'tab' || source === 'both';

  running = true;
  stopping = false;
  finished = false;
  savedMd = '';
  clearLog();
  els.openFolder.classList.add('hidden');
  els.banner.classList.add('hidden');
  els.timer.textContent = '00:00:00';
  els.toggle.textContent = 'Ferma';
  for (const e of [els.source, els.model, els.title, els.glossary]) e.disabled = true;
  setStatus('Preparo l\'audio', true);

  // 1) audio first, inside the user gesture, before the WebSocket
  try {
    try {
      audioCtx = new AudioContext({ sampleRate: 16000 });
    } catch (e) {
      audioCtx = new AudioContext();
    }
    audioCtx.resume().catch(() => {});

    let screenStream = null;
    // display capture first: it needs a fresh user gesture
    if (wantTab) {
      screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      streams.push(screenStream);
      if (screenStream.getAudioTracks().length === 0) {
        fail('Nessun audio condiviso: riprova e spunta «Condividi anche l\'audio della scheda»');
        return;
      }
      screenStream.getVideoTracks().forEach((t) => {
        t.applyConstraints({ frameRate: 1 }).catch(() => {});
      });
    }
    if (wantMic) {
      const mic = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true,
                 autoGainControl: true },
      });
      streams.push(mic);
    }

    await audioCtx.audioWorklet.addModule('/static/worklet.js');
    const node = new AudioWorkletNode(audioCtx, 'pcm-sender', {
      numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1, channelCountMode: 'explicit',
    });
    const gainValue = streams.length > 1 ? 0.7 : 1;
    for (const s of streams) {
      if (s.getAudioTracks().length === 0) continue;
      const src = audioCtx.createMediaStreamSource(new MediaStream(s.getAudioTracks()));
      const gain = audioCtx.createGain();
      gain.gain.value = gainValue;
      src.connect(gain);
      gain.connect(node);
    }
    node.port.onmessage = (ev) => {
      els.level.style.width = Math.min(100, ev.data.rms * 400) + '%';
      if (sending && ws && ws.readyState === 1) ws.send(ev.data.pcm);
    };

    if (screenStream) {
      screenStream.getAudioTracks()[0].addEventListener('ended', () => {
        if (running && !stopping) stop('Condivisione terminata. ');
      });
    }
  } catch (err) {
    const name = err && err.name;
    if (name === 'NotAllowedError' || name === 'AbortError') {
      fail(wantTab ? 'Selezione annullata' : 'Accesso al microfono negato');
    } else {
      fail('Errore: ' + ((err && err.message) || name || 'audio non disponibile'));
    }
    return;
  }

  // 2) only now the WebSocket
  ws = new WebSocket(`ws://${location.host}/ws`);
  sending = false;
  ws.onopen = () => {
    ws.send(JSON.stringify({
      type: 'start', model: els.model.value, source,
      title: els.title.value.trim(), glossary: els.glossary.value.trim(), language: 'it',
    }));
    setStatus('Caricamento modello', true);
  };
  ws.onmessage = (ev) => onServerMessage(JSON.parse(ev.data));
  ws.onclose = () => {
    if (!finished && running) fail('Connessione persa');
    ws = null;
  };

  try {
    wakeLock = await navigator.wakeLock.request('screen');
  } catch (e) { /* optional */ }
  window.addEventListener('beforeunload', onBeforeUnload);
}

function stop(prefix = '') {
  if (!running || stopping) return;
  stopping = true;
  sending = false;
  els.toggle.disabled = true;
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ type: 'stop' }));
    setStatus(prefix + 'Elaboro l\'audio rimasto', true);
  } else {
    fail(prefix.trim() || 'Interrotto');
    return;
  }
  // stop capturing now; the socket stays open until `saved`
  const keepWs = ws;
  releaseAudio();
  ws = keepWs;
}

// ---------- server messages ----------

function onServerMessage(m) {
  switch (m.type) {
    case 'status':
      setStatus(m.text.replace(/\.+$/, ''), !!m.busy);
      break;
    case 'ready':
      sending = !stopping;
      startTimer();
      setStatus('In ascolto');
      break;
    case 'paragraph':
      addParagraph(m.start, m.text);
      break;
    case 'current':
      setCurrent(m.start, m.text);
      break;
    case 'lag':
      if (m.seconds > 15) {
        els.banner.textContent = `Il modello non regge il tempo reale (ritardo ~${Math.round(m.seconds)} s). ` +
                                 'Per la prossima sessione prova «small».';
        els.banner.classList.remove('hidden');
      } else if (m.seconds < 5) {
        els.banner.classList.add('hidden');
      }
      break;
    case 'saved':
      finished = true;
      savedMd = m.md;
      releaseAudio();
      resetControls();
      setStatus('Salvato: ' + m.md);
      els.openFolder.classList.remove('hidden');
      if (ws) { try { ws.close(); } catch (e) { /* ignore */ } }
      break;
    case 'error':
      finished = true;
      fail('Errore: ' + m.text);
      break;
  }
}

// ---------- buttons ----------

els.toggle.addEventListener('click', () => {
  if (running) stop(); else start();
});

els.copy.addEventListener('click', async () => {
  const parts = paras.map((p) => `**[${hms(p.start)}]** ${p.text}`);
  if (curr) parts.push(`**[${hms(curr.start)}]** ${curr.text}`);
  try {
    await navigator.clipboard.writeText(parts.join('\n\n'));
    const old = els.copy.textContent;
    els.copy.textContent = 'Copiato';
    setTimeout(() => { els.copy.textContent = old; }, 1200);
  } catch (e) {
    setStatus('Errore: copia non riuscita');
  }
});

els.openFolder.addEventListener('click', () => {
  fetch('/open-folder', { method: 'POST' }).catch(() => {});
});

checkSupport();
