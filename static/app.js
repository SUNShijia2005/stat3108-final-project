'use strict';
const $ = id => document.getElementById(id);
const all = selector => [...document.querySelectorAll(selector)];
const D = ParcelDrafts;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => Number(value).toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});
const sample = 'SHIP24_SAMPLE_DELIVERED_000';
const titles = {
  workspace:['需求与对话','和助手聊聊','直接提问、讨论方案，或告诉我这次想怎么寄。'],
  rates:['比较参考方案','比较这次寄件的参考费用','保存包裹信息后，选择一个待核验的参考方案。'],
  documents:['核对寄件文件','把货品和文件核对清楚','先保存草稿，再检查数量、金额和缺少的信息。'],
  summary:['寄件准备清单','查看准备结果和待办','把已确认的信息与仍需核验的项目放在一起。'],
  tracking:['查询物流','用实际运单号查询物流','真实查询与独立官方示例分别显示。'],
  knowledge:['运输问题与依据','查找运输规则','查看适用说明和来源，补充当前寄件需求。'],
  evaluation:['项目与评估','实现范围与测试','区分业务工具检查、用户操作和线上模型实验。']
};
const fieldLabels = {origin_province:'起运省市', destination_country:'目的地国家', destination_city:'目的地城市', destination_state:'州代码', destination_zip:'邮编', goods:'货品', weight_kg:'实际重量', length_cm:'长度', width_cm:'宽度', height_cm:'高度', budget_cny:'预算', deadline:'期望送达', residential:'住宅属性', oda_tier:'偏远地区档位', fuel_percent:'燃油比例', items:'货品明细', sender_name:'寄件人姓名', sender_address:'寄件人地址', sender_phone:'寄件人电话', recipient_name:'收件人姓名', recipient_address:'收件人地址', recipient_phone:'收件人电话', currency:'币种', country_of_origin:'原产地', invoice_total:'发票合计'};
const serviceNames = {IE:'国际经济', IP:'国际优先', IPE:'国际优先特快'};
const forms = {rates: $('rate-form'), documents: $('document-form')};
let task, health, busy = false, currentView = 'workspace', drafts = {}, storageAvailable = true;
let lastMessageKey = '', knowledgeLoaded = false, evaluationLoaded = false;
let disabledByBusy = [], modelSettings = null, chatPending = false;

function storageGet(key) { try { return localStorage.getItem(key); } catch { storageAvailable = false; return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); return true; } catch { storageAvailable = false; return false; } }
function storageRemove(key) { try { localStorage.removeItem(key); } catch { storageAvailable = false; } }
function draftStorage() { try { return localStorage; } catch { storageAvailable = false; return null; } }
function draftKey(kind) { return `parcel-draft-v2:${task.id}:${kind}`; }
function toast(message, error = false) {
  $('toast').textContent = message; $('toast').className = 'visible' + (error ? ' error' : '');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { $('toast').className = ''; }, error ? 9000 : 4500);
}
function formError(kind, message) {
  const element = $(kind === 'rates' ? 'rate-error' : kind === 'documents' ? 'document-error' : 'tracking-error');
  element.textContent = message || ''; element.hidden = !message;
}
async function api(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path === '/api/chat' ? 190000 : path === '/api/track' ? 75000 : 15000);
  try {
    const response = await fetch(path, {signal:controller.signal, ...(body !== undefined ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {})});
    const data = await response.json();
    if (!response.ok) {
      if (data.task) { task = data.task; render(); }
      throw new Error(response.status === 409 ? '另一个页面更新了任务。已保留本页草稿，请核对冲突字段后重新填写。' : data.error || '请求未完成，请稍后重试。');
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，草稿仍保留。请重新载入任务核对保存状态后再试。');
    if (error instanceof TypeError) throw new Error('暂时连不上本地服务，草稿仍保留。请确认服务已启动后重试。');
    throw error;
  } finally { clearTimeout(timer); }
}
function setBusy(on, label) {
  busy = on; $('busy-status').hidden = !on || chatPending;
  $('chat-pending').hidden = !on || !chatPending;
  $('busy-status').textContent = on ? label : '';
  document.querySelector('main').setAttribute('aria-busy', String(on));
  if (on) {
    disabledByBusy = [];
    lockNewControls();
  } else {
    disabledByBusy.forEach(el => { if (el.isConnected) el.disabled = false; }); disabledByBusy = [];
    fitConversation();
  }
}
function lockNewControls() {
  const controls = all('[data-mutation], form input, form select, form textarea, #import-invoice, #import-packing, #task-history, #add-item, #use-goods, .remove-item, #discard-rates, #discard-documents').filter(el => !el.disabled);
  controls.forEach(el => { el.disabled = true; });
  disabledByBusy.push(...controls);
}
async function run(label, operation, errorKind) {
  if (busy) { toast('正在处理上一步，请稍候。'); return; }
  if (errorKind) formError(errorKind, '');
  setBusy(true, label);
  try { await operation(); }
  catch (error) { if (errorKind) formError(errorKind, error.message); toast(error.message, true); }
  finally { setBusy(false); renderDraftStatus(); }
}
function normalizeItem(item) {
  const out = {};
  for (const key of ['description','quantity','packing_quantity','unit_price','hs_code']) {
    const value = item[key];
    out[key] = ['quantity','packing_quantity','unit_price'].includes(key) ? (value === '' || value == null ? null : Number(value)) : String(value ?? '');
  }
  return out;
}
function savedValues(kind) {
  const values = {};
  for (const element of forms[kind].elements) {
    if (!element.name) continue;
    let value = task.fields[element.name];
    if (value == null || value === '') value = element.name === 'destination_country' ? 'US' : element.name === 'oda_tier' ? 'unknown' : null;
    values[element.name] = value;
  }
  if (kind === 'documents') values.items = (task.fields.items || []).map(normalizeItem);
  return values;
}
function fill(form, values) {
  for (const element of form.elements) if (element.name) element.value = values[element.name] == null ? '' : String(values[element.name]);
}
function collect(form) {
  const out = {};
  for (const element of form.elements) if (element.name) {
    const value = element.value.trim();
    out[element.name] = value === '' ? null : element.type === 'number' ? Number(value) : element.name === 'residential' ? value === 'true' : value;
  }
  return out;
}
function readItems() {
  return [...$('item-rows').rows].map(row => normalizeItem(Object.fromEntries([...row.querySelectorAll('input')].map(el => [el.dataset.field, el.value]))))
    .filter(row => Object.values(row).some(value => value !== null && value !== ''));
}
function formValues(kind) {
  const values = collect(forms[kind]); if (kind === 'documents') values.items = readItems(); return values;
}
function dirty(kind) { return !!drafts[kind]; }
function rememberDraft(kind) {
  if (!task) return;
  const base = drafts[kind]?.base || savedValues(kind), values = formValues(kind);
  if (Object.keys(D.changedFields(base, values)).length) {
    drafts[kind] = {base:D.clone(base), values};
    if (!D.saveDraft(draftStorage(), draftKey(kind), drafts[kind])) storageAvailable = false;
  } else { delete drafts[kind]; storageRemove(draftKey(kind)); }
  renderDraftStatus();
  if (kind === 'rates') renderQuote();
  else { clearFieldErrors(); renderChecks(); }
}
function restoreDrafts() {
  drafts = {};
  for (const kind of Object.keys(forms)) {
    const record = D.loadDraft(draftStorage(), draftKey(kind));
    if (record && Object.keys(D.changedFields(record.base, record.values)).length) drafts[kind] = record;
  }
}
function discardDraft(kind) {
  delete drafts[kind]; storageRemove(draftKey(kind)); formError(kind, ''); render();
  toast('本页已恢复为任务中保存的内容。');
}
function fieldsForSave(kind) {
  if (!drafts[kind]) return {};
  const merge = D.mergeDraft(drafts[kind].base, formValues(kind), savedValues(kind));
  if (merge.conflicts.length) throw new Error('任务中的这些字段也已改变：' + merge.conflicts.map(k => fieldLabels[k] || k).join('、') + '。草稿已保留，请核对或放弃本页修改后重填。');
  return merge.patch;
}
async function action(path, body = {}, committedKind) {
  const data = await api(path, {id:task.id, version:task.version, ...body});
  if (committedKind) { delete drafts[committedKind]; storageRemove(draftKey(committedKind)); }
  task = data.task; render(); updateCurrentHistory(); return data.output;
}
function go(view) {
  currentView = view;
  all('.view').forEach(el => el.classList.toggle('active', el.id === 'view-' + view));
  all('.nav').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  [$('current-view').textContent, $('page-title').textContent, $('page-subtitle').textContent] = titles[view];
  window.scrollTo({top:0, behavior:'auto'});
  if (view === 'workspace') fitConversation();
  if (view === 'summary') renderSummary();
  if (view === 'knowledge' && !knowledgeLoaded) loadKnowledge().catch(error => toast(error.message, true));
  if (view === 'evaluation' && !evaluationLoaded) loadEvaluation().catch(error => toast(error.message, true));
}
function refs(rows) {
  return rows?.length ? '<details class="references"><summary>查看依据（' + rows.length + '）</summary><div class="source-chips">' + rows.map(d => '<a target="_blank" rel="noopener noreferrer" href="' + esc(d.source_url) + '">' + esc(d.title || d.id) + (d.page ? ' · p.' + esc(d.page) : '') + ' ↗</a>').join('') + '</div></details>' : '';
}
function renderMessages() {
  const messages = task.messages || [], previousScroll = $('messages').scrollTop;
  const key = task.id + ':' + messages.length;
  $('messages').innerHTML = messages.length ? messages.map(m => {
    const changes = m.changes?.length ? '<div class="change-box">已更新：' + m.changes.map(c => esc(c.label || fieldLabels[c.field] || c.field) + ' ' + esc(c.before ?? '未填写') + ' → ' + esc(c.after ?? '未填写')).join('；') + '</div>' : '';
    const scenario = m.scenario?.differences?.length ? '<div class="scenario-box"><b>情景比较</b>' + m.scenario.differences.map(d => '<div>' + esc(d.service) + '：¥' + money(d.after) + '（' + (d.delta < 0 ? '减少 ' : '增加 ') + '¥' + money(Math.abs(d.delta)) + '）</div>').join('') + '</div>' : '';
    const trace = m.trace?.length ? '<details class="trace"><summary>处理记录（' + m.trace.length + '步）</summary>' + m.trace.map(t => '<p>' + esc(({update_shipment:'更新需求',estimate_rates:'计算参考费用',search_rules:'检索资料',check_documents:'核对文件',track_demo:'读取官方示例',estimate_scenario:'试算方案'})[t.tool] || t.tool) + ' · ' + esc(t.duration_ms) + ' ms</p>').join('') + '</details>' : '';
    const connection = m.role === 'assistant' && (m.model_error || m.connection_required) ? '<div class="message-connection">' + (m.model_error ? '<span>AI 连接未成功：' + esc(m.model_error) + '</span>' : '') + '<button class="text-button" type="button" data-model-settings>' + (m.model_error ? '检查 AI 设置' : '启用 AI 对话') + '</button></div>' : '';
    return '<div class="message ' + (m.role === 'user' ? 'user' : '') + '"><span class="message-icon">' + (m.role === 'user' ? '你' : '↗') + '</span><div class="message-body">' + (m.role === 'user' ? '' : '<div class="message-label">助手</div>') + '<div class="message-text">' + esc(m.text) + '</div>' + connection + changes + scenario + refs(m.citations) + trace + '</div></div>';
  }).join('') : '<div class="message"><span class="message-icon">↗</span><div class="message-body"><div class="message-label">寄件助手</div><div class="message-text">你好！想先聊点什么？\n\n你可以直接提问，也可以告诉我寄件的想法，我们一起整理。</div></div></div>';
  const container = $('messages'), latest = container.lastElementChild;
  // Start a new answer where its text begins, including on short screens.
  container.scrollTop = key !== lastMessageKey && latest
    ? container.scrollTop + latest.getBoundingClientRect().top - container.getBoundingClientRect().top - 10
    : previousScroll;
  lastMessageKey = key;
}
function renderDraftStatus() {
  if (!task) return;
  const dirtyNames = [];
  for (const kind of Object.keys(forms)) {
    const element = $(kind === 'rates' ? 'rate-draft-status' : 'document-draft-status');
    if (!drafts[kind]) { element.textContent = ''; continue; }
    dirtyNames.push(kind === 'rates' ? '包裹信息' : '单证');
    const merged = D.mergeDraft(drafts[kind].base, drafts[kind].values, savedValues(kind));
    element.textContent = (storageAvailable ? '本机草稿已保留，尚未保存到任务。' : '草稿暂存在当前页面，浏览器存储不可用，请及时保存。') + (merged.conflicts.length ? ' 与任务当前版本冲突：' + merged.conflicts.map(k => fieldLabels[k] || k).join('、') + '。' : ' 切换页面后仍会保留。');
  }
  $('save-status').textContent = dirtyNames.length ? dirtyNames.join('、') + '有未保存草稿' : (task.is_demo ? '示例任务 · 已保存' : '任务已保存');
}
function itemRow(item = {}) {
  const row = document.createElement('tr');
  row.innerHTML = ['description','quantity','packing_quantity','unit_price','hs_code'].map((key, i) => '<td><input aria-label="' + ['货品描述','发票数量','装箱数量','单价','HS 编码'][i] + '" data-field="' + key + '" ' + (i > 0 && i < 4 ? 'type="number" min="' + (i === 3 ? '0.01' : '1') + '" step="' + (i === 3 ? '.01' : '1') + '"' : 'type="text"') + ' value="' + esc(item[key] ?? '') + '"></td>').join('') + '<td><button type="button" class="remove-item" aria-label="删除货品行">×</button></td>';
  row.querySelector('button').onclick = () => { row.remove(); rememberDraft('documents'); };
  $('item-rows').append(row);
}
function clearFieldErrors() {
  all('.field-error').forEach(el => el.remove());
  all('.field-invalid').forEach(el => { el.classList.remove('field-invalid'); el.removeAttribute('aria-invalid'); });
}
function issueElement(issue) {
  if (issue.field === 'items') return $('item-rows').querySelector('[data-field="description"]') || $('add-item');
  if (issue.item_index != null) return $('item-rows').rows[issue.item_index]?.querySelector('[data-field="' + CSS.escape(issue.field || 'description') + '"]');
  return forms.documents.querySelector('[name="' + CSS.escape(issue.field || '') + '"]');
}
function renderChecks() {
  clearFieldErrors();
  if (dirty('documents')) { $('document-output').innerHTML = '<div class="draft-status">单证有未保存修改，保存并检查后显示最新核对结果。</div>'; return; }
  const check = task.checks;
  if (!check) { $('document-output').innerHTML = ''; return; }
  $('document-output').innerHTML = '<article class="card check-result ' + (!check.issues.length ? 'good' : '') + '"><div class="card-head"><h2>' + (!check.issues.length ? '基础字段和数量、金额核对通过' : '需要修正 ' + check.issues.length + ' 项信息') + '</h2><span class="pill">合计 ' + money(check.calculated_total) + ' ' + esc(check.currency || '') + '</span></div>' + check.issues.map((issue, i) => '<button class="issue" data-issue="' + i + '">↳ ' + esc(issue.message) + '</button>').join('') + '<p class="quote-note">后续核对：' + check.review_items.map(esc).join('；') + '。</p><button class="button secondary" data-go="summary">查看准备清单 →</button></article>';
  check.issues.forEach(issue => {
    const elements = [issueElement(issue)];
    for (const field of issue.related_fields || []) {
      if (issue.item_index != null) elements.push($('item-rows').rows[issue.item_index]?.querySelector('[data-field="' + CSS.escape(field) + '"]'));
    }
    [...new Set(elements.filter(Boolean))].forEach(el => {
      el.classList.add('field-invalid'); el.setAttribute('aria-invalid','true');
      const message = document.createElement('span'); message.className = 'field-error'; message.textContent = issue.message; el.after(message);
    });
  });
}
function renderQuote() {
  const quote = task.quote;
  const unsaved = dirty('rates') ? '<div class="draft-status">包裹信息有未保存修改。下方为上次保存的估算，请保存并重新估算后再选择方案。</div>' : '';
  if (!quote) { $('quote-output').innerHTML = unsaved + '<div class="empty-state"><h2>补齐信息后比较费用</h2><p>需要起运省市、具体货品、美国邮编、实际重量和长宽高。</p></div>'; return; }
  if (quote.status !== 'estimated') { $('quote-output').innerHTML = unsaved + '<article class="card"><span class="pill amber">尚不能生成参考方案</span><h2>' + esc(quote.message) + '</h2><p class="quote-note">补充信息或核对适用条件后，再保存并估算。</p></article>'; return; }
  $('quote-output').innerHTML = unsaved + '<div class="weight-summary"><div><small>实际重量</small><strong>' + quote.actual_kg + ' kg</strong></div><div><small>体积重量</small><strong>' + quote.volumetric_kg + ' kg</strong></div><div><small>计费重量 · 区 ' + quote.zone + '</small><strong>' + quote.billable_kg + ' kg</strong></div></div>' + quote.options.map((option, i) => {
    const selected = task.selected_service?.service === option.service;
    return '<article class="quote-card ' + (selected ? 'selected' : '') + '"><div class="quote-heading"><div><span class="service-code">' + esc(option.service) + '</span><h3 class="service-name">' + esc(serviceNames[option.service] || option.name) + '</h3>' + (i === 0 ? '<span class="pill">最低已知参考小计</span>' : '') + '</div><div class="price"><small>参考小计 · 人民币</small>¥' + money(option.known_subtotal) + '</div></div><details class="advanced"><summary>查看费用组成及来源</summary>' + option.components.map(c => '<div class="cost-row"><span>' + esc(c.label) + '</span><strong>¥' + money(c.amount) + '</strong></div>').join('') + '<a target="_blank" rel="noopener" href="' + esc(option.source_url) + '">来源费率表 · 第 ' + option.source_page + ' 页 ↗</a></details><div class="quote-meta"><span>' + ({unknown:'未设置预算',over:'已知费用已超预算',within_known_cost:'已知小计在预算内，另有待确认费用'}[option.budget_status]) + '</span></div><div class="quote-foot"><span class="quote-note">时效与地址覆盖待核验</span><button class="button ' + (selected ? 'secondary' : 'primary') + '" data-select="' + esc(option.service) + '" data-mutation ' + (dirty('rates') ? 'disabled' : '') + '>' + (selected ? '已选参考方案 ✓' : '选择此参考方案') + '</button></div></article>';
  }).join('') + '<article class="card"><h3>确定最终费用前还需要核对</h3><ul class="pending-list">' + quote.pending.map(p => '<li>' + esc(p) + '</li>').join('') + '</ul><details class="advanced"><summary>费率适用范围与日期</summary><p>单件自备包装，广东和福建以外的中国大陆出口。账户与付款资格需确认。费率版本自 ' + esc(quote.effective_from) + ' 生效，资料收集于 ' + esc(quote.source_collected_on) + '。燃油情景只作用于基础运费，未在线核验。</p></details></article>';
}
function renderTracking() {
  const tracking = task.tracking;
  if (!tracking) { $('tracking-output').innerHTML = '<div class="empty-state"><h2>当前任务尚未关联物流结果</h2><p>填写真实运单号进行查询，或展开上方的独立官方示例。</p></div>'; return; }
  const demo = tracking.data_type === 'official_synthetic_sample';
  $('tracking-output').innerHTML = '<div class="tracking-layout"><article class="card tracking-status"><span class="pill ' + (demo ? 'amber' : 'green') + '">' + (demo ? '独立示例 · 与本任务无关联' : 'Ship24 查询结果') + '</span><h2>' + esc(({delivered:'已送达',in_transit:'运输中',pending:'等待更新'})[tracking.status] || tracking.status || '状态待更新') + '</h2><p>' + esc(tracking.tracking_number) + '</p>' + (demo ? '<p>法国官方模拟轨迹，仅展示查询形式。</p>' : '') + '<p>查询记录时间<br>' + esc(tracking.queried_at) + '</p></article><article class="card"><div class="card-head"><h2>物流事件（' + tracking.events.length + '）</h2><a target="_blank" rel="noopener" href="' + esc(tracking.source_url) + '">状态说明 ↗</a></div><div class="timeline">' + tracking.events.map(event => '<div class="timeline-event"><small>' + esc(event.occurrenceDatetime) + '</small><h3>' + esc(event.status || event.statusMilestone || '物流更新') + '</h3><p>' + esc(typeof event.location === 'object' ? JSON.stringify(event.location) : event.location) + '</p></div>').join('') + '</div></article></div>';
}
function renderProgress() {
  const progress = task.progress;
  if (!progress) { $('task-progress').textContent = ''; return; }
  const views = {details:'rates', service:'rates', documents:'documents', summary:'summary'};
  $('task-progress').innerHTML = progress.steps.map((step, i) => '<button class="step ' + esc(step.status) + '" data-go="' + views[step.id] + '"><b>' + (step.status === 'complete' ? '✓' : i + 1) + '</b><span>' + esc(step.title) + '<small>' + esc(step.description) + '</small></span></button>').join('');
  const step = progress.steps.find(s => s.status === 'current');
  $('next-step').textContent = step?.description || '可以查看已整理的准备清单。';
  $('next-action').textContent = ({rates:task.quote?.status === 'estimated' ? '比较并选择参考方案' : '补充信息并估算',documents:'核对寄件文件',summary:'查看准备清单'})[progress.next_view] || '继续准备';
}
function renderSummary() {
  const selected = task.selected_service, progress = task.progress;
  const pendingDrafts = dirty('rates') || dirty('documents');
  $('summary-output').innerHTML = (pendingDrafts ? '<div class="draft-status">你还有未保存草稿。下面仅显示任务中已保存的内容，请先保存并检查后再打印。</div>' : '') + '<article class="card"><div class="card-head"><div><h2>' + (progress?.ready_for_summary && !pendingDrafts ? '寄件准备信息已整理' : '还有信息需要补齐') + '</h2><p>' + (task.is_demo ? '这是虚构示例任务，以下内容用于演示。' : '这份清单记录参考方案、文件检查和下一步核验事项。') + '</p></div><button class="button secondary" id="print-summary" data-mutation>打印／保存准备清单</button></div><div class="summary-grid"><div><h3>包裹与路线</h3><p>' + esc(task.fields.origin_province || '起运地待填写') + ' → ' + esc(task.fields.destination_city || '美国') + ' ' + esc(task.fields.destination_zip || '') + '<br>' + esc(task.fields.goods || '货品待填写') + '<br>' + esc(task.fields.weight_kg ?? '—') + ' kg · ' + [task.fields.length_cm,task.fields.width_cm,task.fields.height_cm].map(v => esc(v ?? '—')).join(' × ') + ' cm</p><h3>参考方案</h3>' + (selected ? '<p>' + esc(selected.service) + ' · ' + esc(serviceNames[selected.service] || selected.name) + '<br>已知参考小计：¥' + money(selected.known_subtotal) + ' CNY</p>' : '<p>尚未选择参考方案。</p><button class="text-button" data-go="rates">去比较并选择方案</button>') + '</div><div><h3>准备进度</h3><ul>' + (progress?.steps || []).filter(s => s.id !== 'summary').map(s => '<li>' + (s.status === 'complete' ? '✓ ' : '○ ') + esc(s.title) + '：' + esc(s.description) + '</li>').join('') + '</ul><h3>向承运人核验</h3><ul>' + (task.quote?.pending || ['服务覆盖、适用价格和最终费用','所需清关文件及送达安排']).map(p => '<li>' + esc(p) + '</li>').join('') + '</ul></div></div><p class="quote-note">准备清单不代表已经寄件或承运人已接受货物。文件仍需核对进口人、HS编码和签字。</p></article>';
}
function render() {
  if (!task) return;
  storageSet('parcel-task-id', task.id);
  $('task-short').textContent = task.is_demo ? '演示任务 · 虚构数据' : '当前寄件任务';
  $('route-origin').textContent = task.fields.origin_province || '待填写';
  $('route-dest').textContent = task.fields.destination_city || '美国 · 待填写';
  $('route-zip').textContent = task.fields.destination_zip ? '美国邮编 ' + task.fields.destination_zip : '美国邮编待填写';
  const f = task.fields;
  $('task-details').innerHTML = [['货品',f.goods],['实际重量',f.weight_kg ? f.weight_kg + ' kg' : null],['尺寸',[f.length_cm,f.width_cm,f.height_cm].every(Boolean) ? [f.length_cm,f.width_cm,f.height_cm].join(' × ') + ' cm' : null],['预算',f.budget_cny != null ? '¥' + money(f.budget_cny) : null],['期望送达',f.deadline]].map(([label,value]) => '<div><dt>' + label + '</dt><dd>' + esc(value || '待填写') + '</dd></div>').join('');
  for (const kind of Object.keys(forms)) {
    const latest = savedValues(kind);
    let values = latest;
    if (drafts[kind]) {
      const rebased = D.rebaseDraft(drafts[kind].base, drafts[kind].values, latest);
      values = rebased.values;
      if (Object.keys(D.changedFields(rebased.base, rebased.values)).length) {
        drafts[kind] = {base:rebased.base, values:rebased.values};
        if (!D.saveDraft(draftStorage(), draftKey(kind), drafts[kind])) storageAvailable = false;
      } else { delete drafts[kind]; storageRemove(draftKey(kind)); }
    }
    fill(forms[kind], values);
    if (kind === 'documents') { $('item-rows').replaceChildren(); (values.items?.length ? values.items : [{}]).forEach(itemRow); }
  }
  $('document-shipment').textContent = '本次货品：' + (f.goods || '待填写') + '；实际重量：' + (f.weight_kg ?? '待填写') + ' kg。' + (task.is_demo ? ' 当前联系人与地址为演示占位信息。' : '');
  $('selected-overview').innerHTML = '<h3>参考方案</h3>' + (task.selected_service ? '<p>' + esc(task.selected_service.service) + ' · ¥' + money(task.selected_service.known_subtotal) + ' CNY<br>已知参考小计，仍有待核验项目。</p><button class="text-button" data-go="summary">查看准备清单 →</button>' : '<p>尚未选择。比较费用后，选一个参考方案继续准备文件。</p><button class="text-button" data-go="rates">查看参考费用 →</button>');
  renderMessages(); renderDraftStatus(); renderQuote(); renderChecks(); renderTracking(); renderProgress(); renderSummary(); fitConversation();
  if (busy) lockNewControls();
}
function fitConversation() {
  if (currentView !== 'workspace') return;
  const card = document.querySelector('.conversation');
  const top = card.getBoundingClientRect().top + window.scrollY;
  card.style.height = Math.max(285, window.innerHeight - top - 16) + 'px';
}
window.addEventListener('resize', fitConversation);
function taskLabel(row) {
  return (row.is_demo ? '示例｜' : '') + (row.origin || '待填起运地') + ' → ' + (row.city || '美国') + '｜' + (row.goods || '新任务') + (row.weight_kg ? ' · ' + row.weight_kg + 'kg' : '') + ' · ' + new Date(row.updated_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}
async function refreshHistory() {
  const rows = (await api('/api/tasks')).tasks;
  $('task-history').innerHTML = rows.map(row => '<option value="' + esc(row.id) + '">' + esc(taskLabel(row)) + '</option>').join('');
  if (task) $('task-history').value = task.id;
}
function updateCurrentHistory() {
  const option = [...$('task-history').options].find(o => o.value === task.id);
  if (option) option.textContent = taskLabel({id:task.id,...task.fields, origin:task.fields.origin_province, city:task.fields.destination_city, updated_at:task.updated_at, is_demo:task.is_demo});
}
async function switchTo(next) {
  if (task) storageSet('parcel-chat-draft:' + task.id, $('chat-message').value);
  task = next; restoreDrafts(); lastMessageKey = '';
  $('chat-message').value = storageGet('parcel-chat-draft:' + task.id) || '';
  $('tracking-number').value = task.tracking?.data_type === 'live_api' ? task.tracking.tracking_number : '';
  $('tracking-live').checked = false;
  for (const kind of ['rates','documents','tracking']) formError(kind, '');
  render(); await refreshHistory(); go('workspace');
}
function renderCards(documents) {
  $('search-output').innerHTML = documents.length ? documents.map(d => '<article class="card knowledge-card"><span class="retrieval-id">' + esc(d.id) + '</span><h3>' + esc(d.title) + '</h3><p>' + esc(d.text) + '</p><div class="source-footer"><span>资料日期 ' + esc(d.source_date || d.date || '见来源') + (d.page ? ' · 第 ' + esc(d.page) + ' 页' : '') + '</span><a target="_blank" rel="noopener" href="' + esc(d.source_url) + '">查看来源 ↗</a></div></article>').join('') : '<article class="card"><h3>没有找到匹配依据</h3><p>请换一个具体问题，例如体积重、货品描述或住宅派送。</p></article>';
}
async function loadKnowledge() { renderCards((await api('/api/sources')).documents); knowledgeLoaded = true; }
async function loadEvaluation() {
  const e = await api('/api/evaluation'); evaluationLoaded = true;
  if (e.status === 'not_run') { $('evaluation-output').innerHTML = '<article class="card"><h2>测试尚未运行</h2></article>'; return; }
  const labels = {RateTests:'费用与范围',DocumentTests:'单证与CSV',WorkflowTests:'任务与对话',HTTPTests:'网页接口',ModelContractTests:'模型接口协议',ChatCorrectnessTests:'对话正确性',TaskFlowTests:'任务流程',ModelConversationTests:'模型对话',ConversationExperienceTests:'对话体验',ModelSettingsTests:'模型设置',ModelSettingsHTTPTests:'模型设置接口'};
  $('evaluation-output').innerHTML = '<div class="eval-grid"><article class="card eval-stat"><small>已记录的 Python 组件测试</small><strong>' + e.passed + ' / ' + e.total + '</strong><span>不等同于完整用户任务准确率</span></article><article class="card eval-stat"><small>线上模型比较</small><strong>尚未运行</strong><span>模型协议使用模拟响应检查</span></article><article class="card eval-stat"><small>结果日期</small><strong>' + esc(e.generated_at?.slice(0,10)) + '</strong><span>固定开发案例，非独立测试集</span></article></div><article class="card"><h2>组件检查</h2><div class="table-scroll"><table class="eval-table"><thead><tr><th>检查范围</th><th>通过／总数</th></tr></thead><tbody>' + Object.entries(e.categories || {}).map(([key,v]) => '<tr><td>' + esc(labels[key] || key) + '</td><td>' + v.passed + ' / ' + v.total + '</td></tr>').join('') + '</tbody></table></div></article><article class="card"><h2>检索比较</h2><p>' + esc(e.retrieval?.count) + ' 条开发问题。结果只反映这组固定问题。</p><table class="eval-table"><thead><tr><th>方法</th><th>Top 1</th><th>Top 3</th></tr></thead><tbody>' + Object.entries(e.retrieval?.methods || {}).map(([key,v]) => '<tr><td>' + esc(key) + '</td><td>' + v.top1 + ' / ' + e.retrieval.count + '</td><td>' + v.top3 + ' / ' + e.retrieval.count + '</td></tr>').join('') + '</tbody></table></article>';
}
function documentReadyToExport() {
  if (dirty('rates')) throw new Error('包裹信息有未保存修改，请先保存并估算，或放弃该页修改，再预览文件。');
}
async function saveDocuments() { await action('/api/documents/check', {fields:fieldsForSave('documents')}, 'documents'); }
function openPrintable(kind) {
  documentReadyToExport();
  const url = (kind === 'summary' ? '/api/export/summary' : '/api/document') + '?id=' + encodeURIComponent(task.id) + (kind === 'summary' ? '' : '&kind=' + kind);
  const title = kind === 'summary' ? '寄件准备清单' : kind === 'invoice' ? '商业发票草稿' : '装箱单草稿';
  $('printable-preview')?.remove();
  const card = document.createElement('article'); card.id = 'printable-preview'; card.className = 'card printable-preview';
  card.innerHTML = '<div class="card-head"><h2>' + title + '</h2><a class="text-button" target="_blank" rel="noopener" href="' + esc(url) + '">在新标签中打开／打印 ↗</a></div><iframe title="' + title + '" src="' + esc(url) + '"></iframe>';
  $(kind === 'summary' ? 'summary-output' : 'document-output').append(card);
  card.scrollIntoView({block:'start',behavior:'smooth'});
}

// Events are attached once; result cards use delegated handlers after rendering.
all('[data-view]').forEach(button => { button.onclick = () => go(button.dataset.view); });
document.addEventListener('click', event => {
  if (event.target.closest('[data-model-settings]')) { openModelSettings(); return; }
  const goButton = event.target.closest('[data-go]'); if (goButton) { go(goButton.dataset.go); return; }
  const choose = event.target.closest('[data-select]');
  if (choose) run('正在保存参考方案…', async () => {
    if (dirty('rates')) throw new Error('请先保存包裹修改并重新估算。');
    await action('/api/select', {service:choose.dataset.select}); go('documents'); toast('参考方案已选，接着核对寄件文件。');
  });
  const issueButton = event.target.closest('[data-issue]');
  if (issueButton) {
    const element = issueElement(task.checks.issues[Number(issueButton.dataset.issue)]);
    if (element) { element.focus(); element.scrollIntoView({block:'center',behavior:'smooth'}); }
  }
  if (event.target.closest('#print-summary')) run('正在打开准备清单…', async () => {
    if (dirty('documents')) throw new Error('单证有未保存修改，请先保存并检查。');
    openPrintable('summary');
  });
});
for (const [kind, form] of Object.entries(forms)) {
  form.addEventListener('input', () => rememberDraft(kind)); form.addEventListener('change', () => rememberDraft(kind));
}
$('chat-message').addEventListener('input', () => { if (task) storageSet('parcel-chat-draft:' + task.id, $('chat-message').value); });
$('chat-form').onsubmit = event => {
  event.preventDefault(); const message = $('chat-message').value.trim(); if (!message || busy) return;
  chatPending = true;
  run('正在回复…', async () => {
    await action('/api/chat', {message}); $('chat-message').value = ''; storageRemove('parcel-chat-draft:' + task.id);
  }).finally(() => { chatPending = false; $('chat-pending').hidden = true; });
};
$('chat-message').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('chat-form').requestSubmit(); } };
all('[data-message]').forEach(button => { button.onclick = () => { if (!busy) { $('chat-message').value = button.dataset.message; $('chat-form').requestSubmit(); } }; });
$('rate-form').onsubmit = event => { event.preventDefault(); run('正在保存包裹并重新估算…', async () => { await action('/api/quote', {fields:fieldsForSave('rates')}, 'rates'); toast(task.quote?.status === 'estimated' ? '参考费用已重新计算，请选择方案。' : '需求已保存，请查看需要补充的信息。'); }, 'rates'); };
$('document-form').onsubmit = event => { event.preventDefault(); run('正在保存并核对文件…', saveDocuments, 'documents'); };
$('discard-rates').onclick = () => { if (!busy) discardDraft('rates'); };
$('discard-documents').onclick = () => { if (!busy) discardDraft('documents'); };
$('add-item').onclick = () => { itemRow(); rememberDraft('documents'); };
$('use-goods').onclick = () => {
  if (!task.fields.goods) { toast('请先在需求中填写货品描述。', true); return; }
  const blank = [...$('item-rows').rows].find(row => !row.querySelector('[data-field="description"]').value.trim());
  if (blank) blank.querySelector('[data-field="description"]').value = task.fields.goods;
  else itemRow({description:task.fields.goods});
  rememberDraft('documents'); toast('已带入描述，请填写实际数量、单价和原产地。');
};
for (const kind of ['invoice','packing']) {
  $('export-' + kind).onclick = () => run('正在保存并准备文件预览…', async () => {
    documentReadyToExport(); await saveDocuments(); openPrintable(kind);
    if (task.checks?.issues.length) toast('草稿含未完成项，已在预览中列出。');
  }, 'documents');
  $('import-' + kind).onchange = event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    run('正在导入 CSV 明细…', async () => {
      if (file.size > 100000) throw new Error('CSV 请控制在100KB内。');
      await action('/api/import', {kind, text:await file.text(), fields:fieldsForSave('documents')}, 'documents');
      toast('明细已导入，请检查数量和价格。');
    }, 'documents');
  };
}
$('tracking-form').onsubmit = event => { event.preventDefault(); run('正在向 Ship24 查询此运单…', async () => { if (!$('tracking-live').checked) throw new Error('请先勾选使用 Ship24 查询此单号。'); const number = $('tracking-number').value.trim(); if (number === sample) throw new Error('这是官方示例单号，请使用下方“查看官方物流示例”。'); await action('/api/track', {number, allow_live:true}); }, 'tracking'); };
$('track-demo').onclick = () => run('正在读取独立官方示例…', () => action('/api/track', {number:sample}));
$('search-form').onsubmit = event => { event.preventDefault(); run('正在检索资料…', async () => { renderCards((await api('/api/search', {query:$('search-query').value, method:$('search-method').value})).results); knowledgeLoaded = true; }); };
$('new-task').onclick = () => run('正在新建寄件任务…', async () => { await switchTo(await api('/api/tasks', {})); toast('新任务已创建，之前的任务可从左侧列表找回。'); });
$('task-history').onchange = () => run('正在载入已有任务…', async () => { const id = $('task-history').value; try { if (id !== task.id) await switchTo(await api('/api/task?id=' + encodeURIComponent(id))); } catch (error) { $('task-history').value = task.id; throw error; } });
$('next-action').onclick = () => go(task.progress?.next_view || 'rates');
$('export-task').onclick = () => {
  const blob = new Blob([JSON.stringify(task, null, 2)], {type:'application/json'}), a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'parcel-task-' + task.id.slice(0,8) + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href),1000);
  if (dirty('rates') || dirty('documents')) toast('导出的是已保存任务；未保存的表单仍在本机草稿中。');
};
$('load-demo').onclick = () => run('正在创建独立示例任务…', async () => {
  await switchTo(await api('/api/tasks', {demo:true}));
  await action('/api/task', {fields:{origin_province:'Shanghai',destination_country:'US',destination_state:'CA',destination_city:'Los Angeles',destination_zip:'90001',goods:'Cotton T-shirts',weight_kg:10,length_cm:30,width_cm:20,height_cm:10,budget_cny:5000,oda_tier:'unknown',currency:'USD',country_of_origin:'CN',invoice_number:'DEMO-001',ship_date:new Date().toLocaleDateString('sv-SE'),sender_name:'Demo Sender',sender_address:'Example origin address · fictitious',sender_phone:'00000000000',recipient_name:'Demo Recipient',recipient_address:'Example destination address · fictitious',recipient_phone:'00000000000',invoice_total:50,items:[{description:'Cotton T-shirt',quantity:2,packing_quantity:2,unit_price:25}]}});
  await action('/api/chat', {message:'请估算当前运费'}); await refreshHistory(); toast('示例任务已载入。可试算重量，或比较并选择参考方案。');
});

function renderModelSettings() {
  const configured = !!modelSettings?.configured;
  $('mode-badge').textContent = configured ? 'AI 已配置' : 'AI 未连接';
  $('mode-note').textContent = configured ? modelSettings.model : '尚未连接 AI 模型';
  $('enable-model').hidden = configured;
  $('open-model-settings').textContent = configured ? 'AI 设置' : '启用 AI 对话';
  $('model-name').value = modelSettings?.model || '';
  $('model-base-url').value = modelSettings?.base_url || 'https://api.openai.com/v1';
  $('model-api-style').value = modelSettings?.api_style || 'responses';
  $('model-key').required = !modelSettings?.has_api_key;
  $('model-key').placeholder = modelSettings?.has_api_key ? '留空保留已保存的密钥' : '填写该服务的 API Key';
  $('model-settings-status').textContent = configured ? '已配置 ' + modelSettings.model : '';
}
async function loadModelSettings() {
  modelSettings = await api('/api/model/settings');
  renderModelSettings();
}
function openModelSettings() {
  $('model-setup').hidden = false;
  $('model-setup').scrollIntoView({block:'start',behavior:'smooth'});
  $('model-name').focus({preventScroll:true});
  fitConversation();
}
$('open-model-settings').onclick = openModelSettings;
$('enable-model').onclick = openModelSettings;
$('close-model-settings').onclick = () => { $('model-setup').hidden = true; fitConversation(); };
$('model-settings-form').onsubmit = event => {
  event.preventDefault();
  const error = $('model-settings-error'); error.hidden = true; error.textContent = '';
  const values = Object.fromEntries(new FormData($('model-settings-form')));
  run('正在保存 AI 设置…', async () => {
    try {
      await api('/api/model/settings', values);
      $('model-key').value = '';
      health = await api('/api/health'); await loadModelSettings();
      $('model-setup').hidden = true; fitConversation();
      toast('设置已保存，下一条消息会尝试使用 ' + modelSettings.model + '。');
    } catch (failure) {
      error.hidden = false; error.textContent = failure.message; throw failure;
    }
  });
};

(async () => {
  try {
    health = await api('/api/health');
    await loadModelSettings();
    const id = storageGet('parcel-task-id'); let restored;
    if (id) { try { restored = await api('/api/task?id=' + encodeURIComponent(id)); } catch (error) { if (!error.message.includes('不存在')) throw error; } }
    await switchTo(restored || await api('/api/tasks', {}));
  } catch (error) { $('save-status').textContent = '连接失败'; $('messages').innerHTML = '<div class="form-error">' + esc(error.message) + ' <button class="text-button" onclick="location.reload()">重新连接</button></div>'; toast(error.message, true); }
})();
