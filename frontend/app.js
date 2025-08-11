/* global cytoscape */
const bilkent = window.cytoscapeCoseBilkent || window.coseBilkent;
if (bilkent) {
  cytoscape.use(bilkent);
} else {
  console.warn('cose-bilkent plugin not found; falling back to breadthfirst');
}

const urlEl = document.querySelector('#url');
const goBtn = document.querySelector('#go');
const bar = document.querySelector('#bar');
const meta = document.querySelector('#meta');
const details = document.querySelector('#details');
const info = document.querySelector('#info');
document.querySelector('#closePanel').addEventListener('click', ()=> details.hidden = true);

let cy;

function initCy(){
  const container = document.getElementById('cy');
  if (!container) throw new Error('#cy not found');
  cy = cytoscape({
    container,
    elements: [],
    minZoom: 0.2,
    maxZoom: 2.5,
    style: [
      { selector: 'node',
        style: {
          'background-color': '#94a3b8',
          'label': 'data(label)',
          'text-valign': 'center',
          'color': '#1f2937',
          'text-background-color': '#ffffff',
          'text-background-opacity': 1,
          'text-background-padding': 3,
          'border-width': 2,
          'border-color': '#e5e7eb',
          'font-size': 10
        }
      },
      { selector: 'node[status >= 400]',
        style: {'background-color': '#ef4444', 'border-color':'#fecaca'} },
      { selector: 'node[status >= 300][status < 400]',
        style: {'background-color': '#f59e0b', 'border-color':'#fde68a'} },
      { selector: 'node[status >= 200][status < 300]',
        style: {'background-color': '#22c55e', 'border-color':'#bbf7d0'} },
      { selector: 'edge',
        style: { 'width': 2, 'line-color': '#cbd5e1', 'target-arrow-color':'#cbd5e1', 'target-arrow-shape':'triangle' } }
    ],
    layout: { name: (window.cytoscapeCoseBilkent || window.coseBilkent) ? 'cose-bilkent' : 'breadthfirst', animate: false }
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

async function enumerate(){
  const target = urlEl.value.trim();
  if (!target) return;
  setProgress(0); showProgress(true); meta.textContent = '';
  cy.elements().remove();

  const resp = await fetch('/api/enumerate', {
    method: 'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ url: target })
  });
  const { job_id } = await resp.json();

  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/${job_id}`);

  ws.onmessage = (ev)=>{
    const msg = JSON.parse(ev.data);
    if (msg.type === 'progress'){
      setProgress(msg.value);
    } else if (msg.type === 'meta'){
      meta.textContent = `lists: ${msg.wordlists.map(x=>x.split('/').slice(-2).join('/')).join(', ')} | candidates: ${msg.total_candidates}`;
    } else if (msg.type === 'done'){
      const g = msg.result;
      cy.add(g.nodes);
      cy.add(g.edges);
      cy.layout({ name: 'cose-bilkent', animate:false }).run();
      setProgress(1);
      setTimeout(()=> showProgress(false), 400);
      ws.close();
    }
  };
}

goBtn.addEventListener('click', enumerate);
urlEl.addEventListener('keydown', (e)=> { if (e.key === 'Enter') enumerate(); });
