'use strict';
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
let boot, current = null, state = null, stream = null, selectedTemplate = 'ministry_light', showingDeck = false, refreshTimer, currentCitation = null, refreshSequence = 0;
const screen = $('#chat-screen');
function toast(message) { const box = $('#toast'); box.textContent = message; box.hidden = false; clearTimeout(box.timer); box.timer = setTimeout(() => box.hidden = true, 10000); }
async function api(path, value) {
  const response = await fetch(path, value === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Matn-Token': boot.token}, body: JSON.stringify(value)});
  const result = await response.json(); if (!response.ok) throw Error(result.error || 'The request did not complete'); return result;
}
async function loadBootstrap() {
  boot = await api('/api/bootstrap');
  $('#chat-count').textContent = boot.conversations.length;
  const history = $('#conversations'); history.replaceChildren();
  for (const c of boot.conversations) { const b = el('button', 'conversation' + (c.id === current ? ' selected' : ''), c.title); b.onclick = () => openConversation(c.id); b.title = c.title; history.append(b); if (c.id === current) { const actions = el('div', 'history-actions'); const rename = el('button', 'quiet', 'Rename'), remove = el('button', 'quiet', 'Delete'); rename.onclick = () => $('#rename-chat').click(); remove.onclick = () => $('#delete-chat').click(); actions.append(rename, remove); history.append(actions); } }
  const check = boot.preflight;
  const ready = $('#readiness'); ready.replaceChildren(el('span', 'local-dot'));
  ready.className = 'readiness' + (boot.fake ? ' fixture' : check.verdict !== 'GO' || check.model.verdict !== 'GO' ? ' warn' : '');
  ready.append(document.createTextNode(boot.fake ? 'FIXTURE MODE · No real model or web searches' : `LOCAL ${check.verdict} · Model ${check.model.verdict} · ${boot.search_remaining} searches allowed`));
  ready.title = check.scope + '\n' + check.model.detail + '\n' + check.checks.filter(r => !r.ok).map(r => r.check + ': ' + (r.detail || 'missing')).join('\n');
  const shortcuts = $('#replay-shortcuts'); shortcuts.replaceChildren();
  for (const name of boot.replays) { const b = el('button', 'replay-button', name + ' ↗'); b.onclick = () => replay(name); shortcuts.append(b); }
  $('#audience').placeholder = boot.default_audience;
  if (!current) renderDeckPanel({active_deck: null, decks: [], catalogs: []});
}
async function ensureConversation() {
  if (current) return current;
  const c = await api('/api/conversations', {audience: $('#audience').value.trim() || undefined});
  current = c.id; connectEvents(); await loadBootstrap(); return current;
}
function chatView() { $('#chat-screen').hidden = false; $('#evaluation-screen').hidden = true; $('#chat-view').classList.add('active'); $('#eval-view').classList.remove('active'); }
async function openConversation(id) { chatView(); currentCitation = null; current = id; document.body.classList.remove('sidebar-open'); connectEvents(); await refresh(); await loadBootstrap(); }
function connectEvents() {
  if (stream) stream.close();
  if (!current) return;
  stream = new EventSource('/api/conversations/' + current + '/events');
  stream.onmessage = () => { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 120); };
}
async function refresh() {
  if (!current) return;
  try {
    const id = current, request=++refreshSequence, c = await api('/api/conversations/' + id); if (current !== id || request!==refreshSequence) return;
    if (state?.id===c.id && state.updated_at>c.updated_at) return;
    const nearBottom = screen.scrollHeight - screen.scrollTop - screen.clientHeight < 200;
    state = c; renderConversation(c);
    if (nearBottom) screen.scrollTop = screen.scrollHeight;
  } catch (e) { toast(e.message); }
}
function textWithCitations(text, citations = []) {
  const result = document.createDocumentFragment(); let start = 0;
  const pattern = /\[([A-Z]*\d+)\]/g;
  for (const match of text.matchAll(pattern)) {
    result.append(document.createTextNode(text.slice(start, match.index)));
    const ref = citations.find(c => c.id === match[1]) || (/^\d+$/.test(match[1]) ? citations[Number(match[1]) - 1] : null);
    if (ref) { const b = el('button', 'citation', '[' + match[1] + ']'); b.title = 'Open exact source span'; b.onclick = () => openCitation(ref); result.append(b); }
    else result.append(document.createTextNode(match[0]));
    start = match.index + match[0].length;
  }
  result.append(document.createTextNode(text.slice(start))); return result;
}
function failureMessage(failure) {
  const detail = failure.detail || failure.error || failure.reason || 'This source could not be read.';
  if (detail.includes('NO_DIGITAL_PAGES_FAKE_MODE_DOES_NOT_RUN_OCR')) return 'This PDF has no readable digital text. Fixture mode does not run OCR.';
  if (detail.includes('NONFINITE_JSON_NUMBER')) return 'This JSON contains a non-finite number. Use a finite numeric value.';
  if (detail.includes('model_unavailable')) return 'The local verifier is unavailable. Earlier verified evidence is retained.';
  return detail;
}
function regionLabel(kind) { return ({body:'Body',footnote:'Footnote',caption:'Caption',toc:'Contents',reference_list:'References',acknowledgement:'Acknowledgements',boilerplate:'Page furniture'})[kind] || kind || 'Body'; }
function renderConversation(c) {
  $('#conversation-title').textContent = c.title;
  $('#rename-chat').hidden = false; $('#delete-chat').hidden = false;
  $('#welcome').hidden = c.messages.length > 0;
  const messages = $('#messages');
  // Preserve focused plan fields while SSE updates the working block.
  if (!document.activeElement.closest('.plan-card')) {
    messages.replaceChildren();
    c.messages.forEach(m => {
      const card = el('article', 'message ' + m.role);
      if (m.role !== 'user') { const h = el('div', 'message-heading'); h.append(el('span', 'message-icon', 'm.'), document.createTextNode('MATN')); if (m.kind) h.append(el('span', 'message-label', ' / ' + m.kind.toUpperCase())); card.append(h); }
      if (m.result?.answer_kind==='generated_source_coverage') card.append(el('p','gap',m.result.message));
      const body = el('div', 'message-body'); const legacyCopy=m.kind==='answer' && (/cop|excerpt/.test(m.result?.answer_kind || '') || m.result?.citations?.some(ref=>['source_copy','source_excerpt'].includes(ref.kind))); body.append(textWithCitations(legacyCopy ? 'This saved response contains source passages. Ask again for a written answer.' : m.text, legacyCopy ? [] : m.result?.citations)); card.append(body);
      if (m.kind === 'answer' && (m.result?.status === 'partial_answer' || m.result?.engine_states?.includes('partial_answer') || (m.result?.answer_kind === 'exact_verified_source_copies' && m.result.metrics?.model_calls > 0))) card.append(el('p', 'gap', 'Partial response. Only the cited, verified content is shown; some requested points remain unestablished.'));
      if (m.result?.retryable && m.result.question) { const retry = el('button','primary','Retry this question'); retry.onclick = () => act({text:m.result.question}); card.append(retry); }
      if (m.kind === 'clarification' && c.pending_research && m.id===c.messages.findLast(x=>x.kind==='clarification')?.id) card.append(clarificationCard(m.clarification));
      if (m.kind === 'plan') card.append(planCard(m.plan, c.plans[c.plans.length - 1]?.created_at === m.plan.created_at));
      if (m.kind === 'deck') { const d = c.decks[m.version - 1]; if (d) card.append(deckCard(d, false)); }
      if (m.result?.proposal && m.result.citations?.length) { const p = el('div', 'plan-card'); p.append(el('div', 'eyebrow', 'PROPOSED PRESENTATION'), el('p', '', m.result.proposal.angle)); const list = el('ol'); m.result.proposal.outline.forEach(x => list.append(el('li', '', x))); p.append(list); const b = el('button', 'primary', 'Make the presentation'); b.onclick = () => act({action: 'build', template: selectedTemplate}); p.append(b); card.append(p); }
      for (const group of m.result?.disagreements || []) { const box = el('div', 'plan-card'); box.append(el('div', 'eyebrow', 'SOURCES SIDE BY SIDE'), el('p', 'message-label', group.label)); const sides = el('div', 'overview-comparison'); group.citations.forEach(ref => { const s = el('div', 'comparison-side'); s.append(el('strong', '', ref.title || ref.file || ref.source), el('p', '', ref.text)); const b = el('button', 'citation', '[' + ref.id + ']'); b.onclick = () => openCitation(ref); s.append(b); sides.append(s); }); box.append(sides); card.append(box); }
      if (m.result?.comparison_status && m.result.citations?.length) card.append(el('p', 'message-label', m.result.comparison_status));
      for (const failure of m.result?.failures || []) card.append(el('p', 'gap', (failure.file || failure.stage || 'Source') + ': ' + failureMessage(failure)));
      if (m.result?.answer_kind) card.append(el('p', 'message-label', (m.result.answer_kind==='generated_answer' ? 'Written answer · sentences checked against cited spans' : m.result.answer_kind.replaceAll('_', ' '))));
      messages.append(card);
    });
  }
  renderWorking(c);
  renderEvidence(c);
  renderDeckPanel(c);
}
function clarificationCard(pending) {
  const box=el('div','plan-card clarification-card');
  const choice=el('select'); choice.setAttribute('aria-label','Intended meaning or audience');
  for (const row of pending.options) { const option=el('option','',row.label); option.value=row.value; choice.append(option); }
  const topic=el('input'); topic.placeholder='Specify the intended topic'; topic.setAttribute('aria-label','Other intended topic');
  const audience=el('input'); audience.placeholder='Who is this briefing for?'; audience.setAttribute('aria-label','Briefing audience');
  const update=()=>{ topic.hidden=!pending.require_topic && (choice.value!=='other' || !pending.needs_meaning); audience.hidden=!pending.needs_audience && !(choice.value==='other' && !pending.needs_meaning); };
  choice.onchange=update; update();
  const submit=el('button','primary','Confirm scope and plan');
  submit.onclick=()=>act({action:'clarify',choice:choice.value,topic:topic.value.trim(),audience:audience.value.trim()});
  box.append(choice,topic,audience,submit); return box;
}
function planCard(item, latest) {
  const box = el('div', 'plan-card'); const facets = structuredClone(item.plan.facets);
  facets.forEach((axis, i) => {
    const row = el('div', 'plan-axis'); row.append(el('label', '', 'AXIS ' + (i + 1)));
    const label = el('input'); label.defaultValue=axis.label; label.value = axis.label; label.setAttribute('aria-label', 'Axis ' + (i + 1) + ' label'); label.oninput = () => axis.label = label.value; label.disabled = !latest;
    const success = el('textarea', 'query-input'); success.rows=2; success.defaultValue=axis.success; success.value = axis.success; success.setAttribute('aria-label', 'Axis ' + (i + 1) + ' success criteria'); success.oninput = () => axis.success = success.value; success.disabled = !latest;
    row.append(label, el('p', '', 'Success criteria'), success);
    const query = el('textarea', 'query-input'); query.rows=2; query.defaultValue=axis.searches.join(' | '); query.value = axis.searches.join(' | '); query.setAttribute('aria-label', 'Axis ' + (i + 1) + ' searches'); query.oninput = () => axis.searches = query.value.split('|').map(x => x.trim()).filter(Boolean); query.disabled = !latest;
    row.append(el('p', '', 'Public search phrases (separate two phrases with |)'), query); box.append(row);
  });
  const actions = el('div', 'plan-actions');
  let approval;
  if (latest && !boot.fake && boot.search_remaining < 12) { const label = el('label', 'search-approval'); approval = el('input'); approval.type = 'checkbox'; label.append(approval, document.createTextNode('Allow up to 12 web searches for this run')); box.append(label); }
  const start = el('button', 'primary', latest ? 'Start research →' : 'Previous plan'); start.disabled = !latest;
  const code = el('select'); code.setAttribute('aria-label', 'Research code'); [['delivery', 'Delivery baseline (live default)'], ['v2', 'Research v2 candidate · acceptance required']].forEach(([v, t]) => { const option = el('option', '', t); option.value = v; code.append(option); });
  start.onclick = () => act({action: 'start', code: code.value, plan: {facets}, approve_searches: approval?.checked === true});
  actions.append(start, code, el('span', 'message-label', 'Up to 12 searches · explicit allowance required'));
  box.append(actions); return box;
}
function renderWorking(c) {
  const live = c.jobs.filter(j => ['running', 'queued'].includes(j.status));
  const box = $('#working'); box.hidden = !live.length;
  if (!live.length) { const index = c.runs.findLastIndex(r => ['running', 'partial', 'interrupted'].includes(r.status)); if (index >= 0) { box.hidden = false; const b = el('button', 'quiet', 'Open saved partial research ↗'); b.onclick = () => act({action: 'open_partial', run: index}); box.replaceChildren(el('span', '', 'Research was interrupted or partial. '), b); } return; }
  const wasOpen = box.querySelector('details')?.open || false;
  const details = el('details'); details.open = wasOpen;
  const foreground=live.find(j=>j.kind!=='Reading files' && j.status==='running') || live[0];
  const summary = el('summary'); summary.append(el('span', 'pulse'), document.createTextNode(foreground.kind + '…'), el('span', 'message-label', live.length > 1 ? `${live.length} active steps` : 'Working'));
  const steps = el('div', 'steps');
  const ids = new Set(live.map(j => j.id));
  const compact=[];
  for (const event of c.events.filter(e => e.kind === 'step' && ids.has(e.detail.job)).slice(-40)) {
    const value=event.detail.summary, last=compact.at(-1), previous=last?.detail.summary;
    if (last && last.detail.job===event.detail.job && typeof value==='object' && typeof previous==='object' && !value.verified && !previous.verified && value.stage===previous.stage && value.file===previous.file) compact[compact.length-1]=event;
    else compact.push(event);
  }
  for (const event of compact) {
    const value = event.detail.summary;
    const step = el('div', 'step');
    if (value?.verified?.length) { step.append(el('strong','',`${value.stage==='checking' ? 'Checking' : 'Drafting'} sentence ${value.sentence || value.verified.length} of ${value.sentences_total || '?'} · verified prose so far`)); for (const ref of value.verified) { const p=el('p'); p.append(textWithCitations(ref.text+' ['+ref.id+']',value.verified)); step.append(p); } }
    else if (typeof value === 'string') step.textContent = value;
    else if (value.stage && value.elapsed_seconds !== undefined) { step.textContent = `${value.stage} · ${value.elapsed_seconds}s · searches ${value.searches}/12 · sources ${value.sources_read}/${value.sources_attempted} · verified units ${value.units_verified}`; if (value.calls_used) step.append(el('div', '', `Generation calls ${value.calls_used.generation ?? 0}/${value.calls_planned?.generation ?? '—'} · native checks ${value.calls_used.native ?? 0}/${value.calls_planned?.native ?? '—'}`)); for (const source of value.sources || []) step.append(el('div', '', `${source.status} · ${source.source_type} · ${source.format || ''} · ${source.url}`)); }
    else { const stages={planning:'Planning answer',drafting:`Drafting sentence ${value.sentence || 1} of ${value.sentences_total || '?'}`,checking:`Checking sentence ${value.sentence || 1} of ${value.sentences_total || '?'}`,reading_source:'Reading source',verifying_source_units:'Verifying main points',answering_from_sources:'Answering from your sources',sources_ready:'Sources ready'}; step.textContent = [stages[value.stage] || value.stage, value.file || value.source, value.completed !== undefined ? `Text pages ${value.completed}/${value.total}` : '', value.ocr_total ? `OCR pages ${value.pages}/${value.ocr_total}` : '', value.units !== undefined ? `${value.units} evidence checks` : ''].filter(Boolean).join(' · '); }
    steps.append(step);
  }
  details.append(summary, steps); box.replaceChildren(details);
}
function renderEvidence(c) {
  if (currentCitation) { renderCitation(currentCitation); return; }
  const box = $('#evidence-content'), refs = c.evidence.citations;
  const count = new Set(refs.map(x => x.doc_id)).size;
  $('#source-count').textContent = (c.metrics.sources || count) + ' SOURCES';
  if (!refs.length && !c.evidence.axes.length) return;
  box.replaceChildren();
  const metrics = el('div', 'metrics');
  [[c.metrics.units || 0, 'verified units'], [c.metrics.sources || 0, 'sources'], [c.metrics.seconds === undefined ? '—' : Math.round(c.metrics.seconds) + 's', 'measured job time'], [c.metrics.generation_calls_incomplete ? 'partial' : c.metrics.generation_calls ?? '—', 'model calls']].forEach(([n, label]) => { const m = el('div', 'metric'); m.append(el('strong', '', n), document.createTextNode(label)); metrics.append(m); }); box.append(metrics);
  for (const axis of c.evidence.axes) if (!axis.units.length) box.append(el('p', 'gap', axis.title + ': no verified units displayed.'));
  for (const gap of c.evidence.gaps) box.append(el('p', 'gap', gap.label + ': ' + (gap.reason || 'Evidence is incomplete.')));
  for (const source of Object.values(c.evidence.regions || {})) { const detail=el('details'); detail.append(el('summary','','Reading regions')); for (const [kind,count] of Object.entries(source.counts)) detail.append(el('p','message-label',regionLabel(kind)+': '+count)); detail.append(el('p','message-label',source.policy)); box.append(detail); }
  refs.forEach(ref => { const item = el('article', 'source-card'); const b = el('button'); b.append(el('span', 'source-kind', ref.source_type+' · '+regionLabel(ref.region)), el('strong', '', ref.title || ref.file || ref.source), el('p', '', 'Open exact source span ↗')); const foot = el('footer'); foot.append(el('span', '', ref.page ? 'Page ' + ref.page : ref.path !== null && ref.path !== undefined ? 'JSON ' + (ref.path || '/') : ref.fetched || 'Date not recorded'), el('span', '', '[' + ref.id + '] ↗')); b.append(foot); b.onclick = () => openCitation(ref); item.append(b); box.append(item); });
}
function artifact(deck, name, conversation = current) { return '/artifacts/' + conversation + '/' + deck.version + '/' + name; }
function deckCard(deck, panel) {
  const box = el('div', 'deck-card');
  const conversation = current;
  const image = el('img'); image.src = artifact(deck, panel ? 'contact-sheet.png' : 'thumbs/slide_01.png', conversation); image.alt = 'Presentation version ' + deck.version + ' slide preview'; image.loading = 'lazy'; image.onerror = () => { if (!image.src.endsWith('contact-sheet.png')) image.src = artifact(deck, 'contact-sheet.png', conversation); else image.hidden = true; }; box.append(image);
  box.append(el('h3', '', 'Presentation · version ' + deck.version), el('small', '', deck.slides + ' slides · ' + deck.template.replaceAll('_', ' ')));
  const status = el('div', 'deck-status'); status.append(el('span', '', deck.status.replaceAll('_', ' ')), el('span', '', '· ' + deck.delivery.replaceAll('_', ' '))); box.append(status);
  box.append(el('small', '', 'Two-renderer QA · Windows / PowerPoint unmeasured'));
  const links = el('div', 'downloads'); [['PPTX ↓', 'deck.pptx'], ['PDF ↓', 'deck.pdf'], ['QA ↗', 'deck_qa.html']].forEach(([text, path]) => { const a = el('a', '', text); a.href = artifact(deck, path); a.target = '_blank'; a.rel = 'noopener'; if (!path.endsWith('html')) a.download = path; links.append(a); }); box.append(links); return box;
}
function renderDeckPanel(c) {
  if (c.active_deck && c.decks[c.active_deck - 1]) selectedTemplate = c.decks[c.active_deck - 1].template;
  const box = $('#deck-content'); box.replaceChildren();
  box.append(el('div', 'eyebrow', 'CHOOSE YOUR DIRECTION'), el('p', 'message-label', 'Three original Matn templates. Every statement stays source-linked.'));
  const options = el('div', 'template-options');
  for (const t of boot.templates) { const b = el('button', 'template-option' + (t.id === selectedTemplate ? ' selected' : '')); b.setAttribute('aria-label', t.name); b.append(el('span', 'template-swatch ' + t.id, 'Aa'), document.createTextNode(t.name)); b.onclick = () => { selectedTemplate = t.id; if (c.active_deck) act({action: 'edit', edit: {op: 'change_template', template: t.id}}); else renderDeckPanel(c); }; options.append(b); }
  box.append(options);
  const build = el('button', 'primary', c.active_deck ? 'Rebuild with current evidence' : 'Make the presentation'); build.disabled = !c.catalogs.length || !c.evidence?.citations.length; build.onclick = () => act({action: 'build', template: selectedTemplate}); box.append(build);
  if (c.active_deck) { const deck = c.decks[c.active_deck - 1], latest=c.decks.at(-1).version; if (deck.version!==latest) { box.append(el('p','viewing-older',`Viewing v${deck.version} (latest v${latest})`)); const newest=el('button','quiet',`View latest v${latest}`); newest.onclick=()=>act({action:'restore',version:latest}); box.append(newest); } box.append(deckCard(deck, true)); const versions = el('div', 'version-list'); c.decks.forEach(d => { const b = el('button', d.version === c.active_deck ? 'selected' : '', 'v' + d.version); b.title = 'View version ' + d.version + (d.version===latest ? ' (latest)' : ''); b.setAttribute('aria-pressed',String(d.version===c.active_deck)); b.onclick = () => act({action: 'restore', version: d.version}); versions.append(b); }); box.append(versions, el('p', 'message-label', 'Try “shorten slide 3”, “move slide 4 first”, or “use the dark template”.'));
  } else box.append(el('div', 'empty-evidence', 'Add documents or open saved research to build your first presentation.'));
}
function openCitation(ref) { currentCitation = ref; panel(false); document.body.classList.add('evidence-open'); renderCitation(ref); }
function renderCitation(ref) {
  const box = $('#evidence-content'); box.replaceChildren(el('h2', '', ref.title || ref.file || 'Source'), el('blockquote', '', ref.quote || ref.text));
  const dl = el('dl');
  const fields = [['Verification', ref.status], ['Source type', ref.source_type], ['File', ref.file], ['Page', ref.page], ['JSON path', ref.path === '' ? '/' : ref.path], ['Fetched', ref.fetched || 'Not recorded'], ['Source span', ref.span?.block_id], ['Offsets', ref.span?.start !== undefined ? `${ref.span.start}–${ref.span.end}` : null], ['Receipt', ref.binding]];
  fields.forEach(([key, value]) => { if (value !== null && value !== undefined && value !== '') dl.append(el('dt', '', key), el('dd', '', String(value))); }); box.append(dl);
  if (ref.url && /^https?:\/\//i.test(ref.url)) { const a = el('a', '', 'Open original source ↗'); a.href = ref.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; box.append(a); }
  for (const span of (ref.spans || []).slice(1)) if (span.quote) box.append(el('p', 'message-label', 'Required source context'), el('blockquote', '', span.quote));
  const back=el('button','quiet','← All sources'); back.onclick=()=>{currentCitation=null;renderEvidence(state);};box.prepend(back);
}
async function act(value) { try { await ensureConversation(); await api('/api/conversations/' + current, value); await refresh(); await loadBootstrap(); } catch (e) { toast(e.message); } }
async function replay(run) { await ensureConversation(); await act({action: 'replay', run}); }
async function newConversation() { currentCitation=null; if (stream) stream.close(); current = null; state = null; $('#messages').replaceChildren(); $('#welcome').hidden = false; $('#working').hidden = true; $('#conversation-title').textContent = 'New conversation'; $('#rename-chat').hidden = true; $('#delete-chat').hidden = true; $('#source-count').textContent = '0 SOURCES'; $('#evidence-content').replaceChildren(el('div', 'empty-evidence', 'Attach sources or start a topic. Exact quotes and verification details appear here.')); $('#deck-content').replaceChildren(); document.body.classList.remove('sidebar-open'); chatView(); await loadBootstrap(); $('#composer-input').focus(); }
$('#composer-form').onsubmit = async event => { event.preventDefault(); const input = $('#composer-input'), text = input.value.trim(); if (!text) return; input.value = ''; await act({action: 'message', text, template: selectedTemplate}); };
$('#composer-input').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#composer-form').requestSubmit(); } };
$('#composer-input').oninput = event => { event.target.style.height = 'auto'; event.target.style.height = Math.min(160, event.target.scrollHeight) + 'px'; };
$('#new-chat').onclick = newConversation; $('#chat-view').onclick = chatView;
$('#welcome-files').onclick = $('#attach-files').onclick = () => $('#file-input').click();
$('#welcome-topic').onclick = () => { $('#composer-input').focus(); $('#composer-input').placeholder = 'What would you like to research?'; };
$('#file-input').onchange = async event => {
  const files = [...event.target.files]; if (!files.length) return;
  $('#attachments').hidden = false; $('#attachments').textContent = 'Preparing ' + files.map(f => f.name).join(', ') + '…';
  try { const values = []; for (const f of files) { if (f.size > 50 * 1024 * 1024) throw Error('Each attachment must be no larger than 50 MiB.'); const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = reject; reader.readAsDataURL(f); }); values.push({name: f.name, data}); } await act({action: 'upload', files: values}); }
  catch (e) { toast(e.message); } finally { $('#attachments').hidden = true; event.target.value = ''; }
};
$('#rename-chat').onclick = async () => { if (!state) return; const title = prompt('Conversation name', state.title); if (title?.trim()) await act({action: 'rename', title}); };
$('#delete-chat').onclick = async () => { if (!state) return; await act({action: 'delete'}); await newConversation(); };
$('#menu-toggle').onclick = () => document.body.classList.toggle('sidebar-open');
$('#nav-scrim').onclick = $('#sidebar-close').onclick = () => document.body.classList.remove('sidebar-open');
document.addEventListener('keydown', event => { if (event.key === 'Escape') document.body.classList.remove('sidebar-open', 'evidence-open'); });
$('#evidence-toggle').onclick = () => document.body.classList.toggle('evidence-open');
$('#close-evidence').onclick = () => document.body.classList.remove('evidence-open');
function panel(deck) { showingDeck = deck; $('#evidence-content').hidden = deck; $('#deck-content').hidden = !deck; $('#evidence-tab').classList.toggle('selected', !deck); $('#deck-tab').classList.toggle('selected', deck); }
$('#evidence-tab').onclick = () => panel(false); $('#deck-tab').onclick = () => panel(true);
$('#close-citation').onclick = () => $('#citation-dialog').close();
$('#citation-dialog').onclick = event => { if (event.target === $('#citation-dialog')) $('#citation-dialog').close(); };
$('#audience-toggle').onclick = () => $('#audience-settings').hidden = !$('#audience-settings').hidden;
$('#audience').onchange = () => { if (current && $('#audience').value.trim()) act({action: 'audience', audience: $('#audience').value.trim()}); };
const theme = localStorage.getItem('matn-theme') || 'light'; document.documentElement.dataset.theme = theme;
$('#theme-toggle').onclick = () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; localStorage.setItem('matn-theme', document.documentElement.dataset.theme); };
document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'k') { event.preventDefault(); newConversation(); } });
function evaluationDetail(run) {
  const box = el('div', 'eval-detail'); box.id = 'eval-run-detail';
  box.append(el('h2', '', run.topic || run.id), el('p', '', 'Review: ' + (run.review_kind || 'unknown') + ' · Silent errors: ' + (run.silent_errors ?? 'unmeasured')));
  const vendor = run.vendor || {};
  box.append(el('p', '', `Calls: generation ${run.calls?.generation ?? 'unknown'}, native ${run.calls?.native ?? 'unknown'} · Searches ${run.searches ?? 'unknown'}`));
  box.append(el('p', '', `Vendor sources: ${vendor.sources_vendor ?? 'unknown'} of ${vendor.sources_total ?? 'unknown'} · First verified unit: ${run.first_verified_seconds === null || run.first_verified_seconds === undefined ? 'unmeasured' : Math.round(run.first_verified_seconds) + 's'}`));
  box.append(el('h3', '', 'Why is an axis empty or partial?'));
  const axes = Array.isArray(run.axes) ? run.axes : [];
  axes.forEach(axis => { const row = el('div', 'gap'); row.append(el('strong', '', axis.label || axis.id), el('p', '', axis.requirement || ''), el('p', '', 'Reviewed coverage: ' + (axis.status || 'unknown') + (axis.review ? ' · ' + (typeof axis.review === 'string' ? axis.review : JSON.stringify(axis.review)) : ''))); if (axis.diagnosis) row.append(el('p', '', 'Earliest loss: ' + (axis.diagnosis.stage || 'unknown') + ' · ' + (axis.diagnosis.reason || 'No diagnosis was saved.')), el('p', 'message-label', 'Suitable evidence present: ' + (axis.diagnosis.suitable_present === null || axis.diagnosis.suitable_present === undefined ? 'unestablished' : axis.diagnosis.suitable_present ? 'yes (AI review)' : 'no (AI review)'))); box.append(row); });
  if (!axes.length) box.append(el('p', '', 'No axis-level review was saved. The cause is unknown.'));
  box.append(el('p', 'message-label', 'A source being read does not establish that an axis is answered. This view preserves the saved review and makes no new semantic judgment.'));
  return box;
}
$('#eval-view').onclick = async () => {
  $('#chat-screen').hidden = true; $('#evaluation-screen').hidden = false; $('#chat-view').classList.remove('active'); $('#eval-view').classList.add('active'); document.body.classList.remove('sidebar-open');
  const box = $('#evaluation-content'); box.replaceChildren(el('p', '', 'Reading saved measurements…'));
  try { const value = await api('/api/evaluation'); const holdouts=typeof value.holdouts==='string' ? value.holdouts : 'Holdouts: '+(value.holdouts?.status || 'UNMEASURED')+(value.holdouts?.reason ? ' — '+value.holdouts.reason : ''); box.replaceChildren(el('p', 'gap', holdouts), el('p', 'message-label', value.review));
    if (value.owner_labels) { const r=value.owner_labels; const labels=el('a','primary','Label evidence →'); labels.href=value.labelling_url; labels.target='_blank'; box.append(el('p','message-label',`${r.owner_labelled} owner-labelled · ${r.pending} AI review / pending owner labels`),labels); for (const [group,result] of Object.entries(r.groups || {})) box.append(el('p','message-label',`${group}: ${result.owner_labelled}/${result.total} owner-labelled · owner subset ${result.owner_verdict}`)); for (const [key,result] of Object.entries(r.verdicts || {})) box.append(el('p','gap',`${key}: ${result.status} · ${result.owner_labelled} owner-labelled / ${result.AI_review} AI review`)); }
    box.append(el('h2', '', 'Your conversations')); const own = el('div', 'metrics'); value.conversations.forEach(c => { const b = el('button', 'metric'); b.append(el('strong', '', c.metrics.units ?? 0), document.createTextNode(c.title)); b.onclick = () => openConversation(c.id); own.append(b); }); box.append(own);
    box.append(el('h2', '', 'Research runs')); const table = el('table', 'score-table'), head = el('thead'), hr = el('tr'); ['RUN', 'UNITS', 'SOURCES', 'TIME', 'STATUS'].forEach(t => hr.append(el('th', '', t))); head.append(hr); table.append(head); const body = el('tbody');
    const runs = value.scoreboard.runs || value.scoreboard.rows || []; const entries = Array.isArray(runs) ? runs : Object.entries(runs).map(([id, r]) => ({id, ...r}));
    entries.forEach(r => { const row = el('tr'); const units = r.units_shown ?? r.units?.displayed ?? r.units?.verified ?? r.units ?? r.verified_units; const sources = r.sources_read ?? r.sources?.read ?? r.sources?.total ?? r.sources; const seconds = r.total_seconds ?? r.wall_seconds ?? r.timing?.total_seconds; const vals = [r.id || r.name || r.run, typeof units === 'object' ? '—' : units ?? '—', typeof sources === 'object' ? '—' : sources ?? '—', seconds === undefined || seconds === null ? '—' : Math.round(seconds) + 's', r.status || r.outcome || 'unknown']; vals.forEach(v => row.append(el('td', '', String(v)))); const open = el('button', 'quiet replay-run', 'Open chat ↗'); open.onclick = async event => { event.stopPropagation(); await newConversation(); await replay(r.id); }; row.firstChild.append(open); row.tabIndex = 0; row.onclick = () => { const old = $('#eval-run-detail'); if (old) old.remove(); table.before(evaluationDetail(r)); }; row.onkeydown = e => { if (e.key === 'Enter') row.click(); }; body.append(row); }); table.append(body); box.append(table);
    box.append(el('h2', '', 'Offline bench'), el('p', 'message-label', value.bench ? value.bench.status + ' · ' + new Date(value.bench.at * 1000).toLocaleString() : 'Not run in this workspace yet. Zero model or search calls.'));
    const savedBench = [...(value.scoreboard.benches || [])].sort((a, b) => b.modified_at - a.modified_at)[0];
    if (savedBench) { box.append(el('p', 'message-label', 'Latest saved retrieval benchmark · ' + new Date(savedBench.modified_at * 1000).toLocaleString() + '. Reference hits are retrieval measurements, not semantic answer accuracy.')); const bt = el('table', 'score-table bench-table'), bh = el('tr'); ['CONFIGURATION', 'HITS', 'DISPLAYED', 'VENDOR SLOTS'].forEach(t => bh.append(el('th', '', t))); const hh = el('thead'); hh.append(bh); bt.append(hh); const bb = el('tbody'); Object.entries(savedBench.summary).forEach(([name, metrics]) => { const row = el('tr'); [name, `${metrics.hit}/${metrics.of}`, `${metrics.displayed_hit}/${metrics.displayed_of}`, `${metrics.vendor_slots}/${metrics.slots}`].forEach(t => row.append(el('td', '', t))); bb.append(row); }); bt.append(bb); box.append(bt); }
  } catch (e) { box.replaceChildren(el('p', 'gap', e.message)); }
};
$('#run-bench').onclick = async () => { await act({action: 'bench'}); toast('Offline bench queued. Open the conversation to follow its progress.'); };
loadBootstrap().then(() => { if (boot.conversations.length) openConversation(boot.conversations[0].id); }).catch(e => toast(e.message));
