/* global cytoscape */
const bilkent = window.cytoscapeCoseBilkent || window.coseBilkent;
if (bilkent) { cytoscape.use(bilkent); } else { console.warn('cose-bilkent not found; using breadthfirst'); }

const urlEl = document.querySelector('#url');
const goBtn = document.querySelector('#go');
const cancelBtn = document.querySelector('#cancel');
const bar = document.querySelector('#bar');
const meta = document.querySelector('#meta');
const details = document.querySelector('#details');
const info = document.querySelector('#info');
document.querySelector('#closePanel').addEventListener('click', ()=> details.hidden = true);

let cy, ws = null, running = false, jobId = null;
let stats = { total: 0, done: 0, found: 0, ok200:0, forb403:0, auth401:0, redir30x:0 };
let t0 = 0;

function initCy(){
  const container = document.getElementById('cy');
  cy = cytoscape({
    container, elements: [], minZoom: 0.2, maxZoom: 2.5,
    style: [
      { selector: 'node', style: {
        'background-color': '#94a3b8','label': 'data(label)','text-valign': 'center','color': '#1f2937',
        'text-background-color': '#ffffff','text-background-opacity': 1,'text-background-padding': 3,
        'border-width': 2,'border-color': '#e5e7eb','font-size': 10
      }},
      { selector: 'node[status >= 400]', style: {'background-color': '#ef4444','border-color':'#fecaca'} },
      { selector: 'node[status >= 300][status < 400]', style: {'background-color': '#f59e0b','border-color':'#fde68a'} },
      { selector: 'node[status >= 200][status < 300]', style: {'background-color': '#22c55e','border-color':'#bbf7d0'} },
      { selector: 'edge', style: { 'width': 2,'line-color': '#cbd5e1','target-arrow-color':'#cbd5e1','target-arrow-shape':'triangle' } }
    ],
    layout: { name: (bilkent ? 'cose-bilkent' : 'breadthfirst'), animate: false }
  });

  cy.on('tap', 'node', (e)=>{
    const d = e.target.data();
    info.innerHTML = `
      <div><strong>Path:</strong> <code>${d.label ?? ''}</code></div>
      ${d.url ? `<div><strong>URL:</strong> <a href="${d.url}" target="_blank">${d.url}</a></div>`:''}
      ${d.status ? `<div><strong>Status:</strong> ${d.status}</div>`:''}
      ${d.issues ? `<div><strong>Issues:</strong> ${d.issues}</div>`:''}
    `;
    details.hidden = false;
  });
}
initCy();

function setProgress(p){ bar.style.width = `${Math.max(0, Math.min(100, Math.round(p*100)))}%`; }
function showProgress(on){ document.getElementById('progressWrap').style.visibility = on ? 'visible' : 'hidden'; }

function setRunning(on){
  running = on;
  goBtn.loading = on;
  goBtn.disabled = on;
  urlEl.disabled = on;
  cancelBtn.hidden = !on;
  if (on) { document.title = '⏳ DirGraph'; showProgress(true); }
  else { document.title = 'DirGraph'; }
}

function fmtBytes(n){
  if (!n && n!==0) return '';
  const u = ['B','KB','MB','GB']; let i=0, x=n;
  while (x>=1024 && i<u.length-1){ x/=1024; i++; }
  return `${x.toFixed(1)} ${u[i]}`;
}

function renderMeta(wordlists){
  const elapsed = running ? ((Date.now() - t0)/1000) : 0;
  const rate = elapsed ? (stats.done/elapsed).toFixed(1) : '0.0';
  const wl = wordlists ? `lists: ${wordlists.map(x=>x.split('/').slice(-2).join('/')).join(', ')}` : '';
  meta.textContent =
    `${wl}${wl ? ' | ' : ''}candidates: ${stats.total} | done: ${stats.done} | found: ${stats.found} ` +
    `(200:${stats.ok200} 403:${stats.forb403} 401:${stats.auth401} 30x:${stats.redir30x}) | ` +
    `rate: ${rate}/s`;
}

async function enumerate(){
  const target = urlEl.value.trim();
  if (!target || running) return;

  stats = { total: 0, done: 0, found: 0, ok200:0, forb403:0, auth401:0, redir30x:0 };
  setProgress(0); showProgress(true); meta.textContent = ''; cy.elements().remove();
  setRunning(true); t0 = Date.now();

  const resp = await fetch('/api/enumerate', {
    method: 'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ url: target })
  });
  const { job_id } = await resp.json();
  jobId = job_id;

  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/${job_id}`);

  ws.onmessage = (ev)=>{
    const msg = JSON.parse(ev.data);

    if (msg.type === 'stage'){
      // Map stages to progress ranges so the bar visibly moves even before scan
      const s = msg.stage;
      if (s === 'seclists_download_start') {
        meta.textContent = 'Downloading SecLists…';
        setProgress(0.02);
      } else if (s === 'seclists_downloading') {
        const pct = msg.total ? (msg.downloaded / msg.total) : 0;
        meta.textContent = `Downloading SecLists… ${fmtBytes(msg.downloaded)} / ${fmtBytes(msg.total)}`;
        setProgress(0.02 + pct * 0.48); // up to 50%
      } else if (s === 'seclists_extract_start') {
        meta.textContent = 'Extracting SecLists…';
        setProgress(0.52);
      } else if (s === 'seclists_extracting') {
        const pct = msg.total ? (msg.done / msg.total) : 0;
        meta.textContent = `Extracting SecLists… ${msg.done}/${msg.total}`;
        setProgress(0.52 + pct * 0.18); // up to 70%
      } else if (s === 'seclists_ready') {
        meta.textContent = 'SecLists ready.';
        setProgress(0.7);
      } else if (s === 'indexing_lists') {
        meta.textContent = 'Indexing wordlists…';
        setProgress(0.72);
      } else if (s === 'probing_target') {
        meta.textContent = 'Probing target…';
        setProgress(0.75);
      } else if (s === 'choosing_wordlists') {
        meta.textContent = 'Choosing wordlists…';
        setProgress(0.78);
      } else if (s === 'building_candidates') {
        meta.textContent = 'Building candidate paths…';
        setProgress(0.80);
      } else if (s === 'soft_404_baseline') {
        meta.textContent = 'Computing soft-404 baseline…';
        setProgress(0.82);
      } else if (s === 'enumeration_started') {
        meta.textContent = 'Enumerating…';
        // progress now switches to true scan progress
      }
    }

    else if (msg.type === 'meta'){
      stats.total = msg.total_candidates || 0;
      renderMeta(msg.wordlists || []);
    }

    else if (msg.type === 'progress'){
      if (stats.total) stats.done = Math.min(stats.total, Math.round(msg.value * stats.total));
      setProgress(0.82 + msg.value * 0.18); // final 18%
      renderMeta();
    }

    else if (msg.type === 'found'){
      stats.found++;
      const s = msg.item?.status;
      if (s >= 200 && s < 300) stats.ok200++;
      else if (s === 403) stats.forb403++;
      else if (s === 401) stats.auth401++;
      else if (String(s).startsWith('30')) stats.redir30x++;
      renderMeta();
    }

    else if (msg.type === 'done'){
      const g = msg.result;
      cy.add(g.nodes); cy.add(g.edges);
      cy.layout({ name: (bilkent ? 'cose-bilkent' : 'breadthfirst'), animate:false }).run();
      setProgress(1);
      finishRun();
    }

    else if (msg.type === 'canceled'){
      meta.textContent = 'Canceled.'; finishRun();
    }

    else if (msg.type === 'error'){
      meta.textContent = `Error: ${msg.message || 'unknown'}`; finishRun();
    }
  };

  ws.onerror = ()=> { meta.textContent = 'WebSocket error.'; finishRun(); };
  ws.onclose = ()=> { if (running) finishRun(); };
}

function finishRun(){
  setRunning(false);
  setTimeout(()=> showProgress(false), 400);
  if (ws) { try { ws.close(); } catch(_){} ws = null; }
  jobId = null;
}

goBtn.addEventListener('click', enumerate);
urlEl.addEventListener('keydown', (e)=> { if (e.key === 'Enter') enumerate(); });

cancelBtn.addEventListener('click', async ()=>{
  if (!jobId) return;
  try { await fetch(`/api/enumerate/${jobId}`, { method: 'DELETE' }); } catch(_) {}
  finishRun();
});
