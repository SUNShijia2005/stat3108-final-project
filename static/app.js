'use strict';
const $ = id => document.getElementById(id);
const all = selector => [...document.querySelectorAll(selector)];
const D = ParcelDrafts;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const money = value => Number(value).toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});
const sample = 'SHIP24_SAMPLE_DELIVERED_000';
const titles = {
  documents:['寄件文件', 'Shipping documents'],
  summary:['寄件准备清单', 'Shipping checklist'],
  knowledge:['寄件帮助', 'Shipping help'],
  evaluation:['项目与评估', 'Project and testing']
};
const paths = {
  workspace:'/', rates:'/shipping', tracking:'/tracking', documents:'/documents',
  summary:'/checklist', knowledge:'/help', evaluation:'/project'
};
const pageHeadings = {workspace:'landing-title', rates:'shipping-title', tracking:'tracking-title'};
const progressSteps = {
  details:['包裹信息','Parcel details','rates'], service:['运输方案','Service','rates'],
  documents:['寄件文件','Documents','documents'], summary:['准备清单','Checklist','summary']
};
const tr = (zh, en) => language === 'en' ? en : zh;
const fieldLabels = {origin_province:'起运省市', destination_country:'目的地国家', destination_city:'目的地城市', destination_state:'州代码', destination_zip:'邮编', goods:'货品', weight_kg:'实际重量', length_cm:'长度', width_cm:'宽度', height_cm:'高度', budget_cny:'预算', deadline:'期望送达', residential:'住宅属性', oda_tier:'偏远地区档位', fuel_percent:'燃油比例', items:'货品明细', sender_name:'寄件人姓名', sender_address:'寄件人地址', sender_phone:'寄件人电话', recipient_name:'收件人姓名', recipient_address:'收件人地址', recipient_phone:'收件人电话', currency:'币种', country_of_origin:'原产地', invoice_total:'发票合计'};
const serviceNames = {IE:'国际经济', IP:'国际优先', IPE:'国际优先特快'};
const forms = {rates: $('rate-form'), documents: $('document-form')};
let task, health, busy = false, currentView = 'workspace', drafts = {}, storageAvailable = true;
let lastMessageKey = '', knowledgeLoaded = false, evaluationLoaded = false;
let disabledByBusy = [], modelSettings = null, chatPending = false;
let language = storageGet('parcel-language') === 'en' ? 'en' : 'zh';
let historyRows = [], drawerTrigger, sampleTracking, inlineCollapsed = false;
const smallScreen = window.matchMedia('(max-width: 670px)');
const wideShipping = window.matchMedia('(min-width: 991px)');
const assistant = $('assistant-drawer');
const translations = [
  ['[data-en]', 'textContent', 'en'],
  ['[data-placeholder-en]', 'placeholder', 'placeholderEn'],
  ['[data-aria-en]', 'aria-label', 'ariaEn']
].flatMap(([selector, key, source]) => all(selector).map(element => ({
  element, key, en:element.dataset[source], zh:key === 'textContent' ? element.textContent : element.getAttribute(key)
})));

function applyLanguage() {
  document.documentElement.lang = tr('zh-CN', 'en');
  for (const {element, key, en, zh} of translations) {
    if (key === 'textContent') element.textContent = tr(zh, en);
    else element.setAttribute(key, tr(zh, en));
  }
  $('language').textContent = tr('EN', '中文');
  $('language').lang = tr('en', 'zh-CN');
  $('language').setAttribute('aria-label', tr('Switch to English', '切换到中文'));
  $('carrier-support').href = 'https://www.fedex.com/' + tr('zh-cn', 'en-cn') + '/customer-support.html';
  updatePageHeading(currentView);
  if (task) {
    renderMessages(); renderDraftStatus(); renderQuote(); renderChecks(); renderTracking(); renderProgress(); renderSummary();
    renderHistory();
    renderAssistantShipment();
  }
  if (modelSettings) renderModelSettings();
}
$('language').onclick = () => {
  language = tr('en', 'zh');
  storageSet('parcel-language', language);
  applyLanguage();
};
applyLanguage();

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
  $('service-panel').setAttribute('aria-busy', String(on && !chatPending));
  if (on) {
    disabledByBusy = [];
    lockNewControls();
  } else {
    disabledByBusy.forEach(el => { if (el.isConnected) el.disabled = false; }); disabledByBusy = [];
  }
}
function lockNewControls() {
  const controls = all('[data-mutation], form input, form select, form textarea, #import-invoice, #import-packing, #task-history, #add-item, #use-goods, .remove-item, #discard-rates, #discard-documents').filter(el => !el.disabled);
  // Chat updates the saved task. The user can keep editing the form draft while it runs.
  const locked = controls.filter(el => !chatPending || !el.matches('#rate-form input, #rate-form select'));
  locked.forEach(el => { el.disabled = true; });
  disabledByBusy.push(...locked);
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
  for (const element of form.elements) {
    if (!element.name) continue;
    const value = values[element.name] == null ? '' : String(values[element.name]);
    if (element.value !== value) element.value = value;
  }
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
  if (kind === 'rates') { renderQuote(); renderProgress(); renderAssistantShipment(); }
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

function viewForPath() {
  return Object.keys(paths).find(view => paths[view] === location.pathname) || 'workspace';
}
function updatePageHeading(view) {
  if (titles[view]) $('page-title').textContent = tr(...titles[view]);
  document.title = view === 'workspace' ? 'Parcel Desk'
    : $(pageHeadings[view] || 'page-title').textContent + ' · Parcel Desk';
}
function showActiveResults() {
  $('quote-output').hidden = !task?.quote;
  $('tracking-output').hidden = !task;
}
function go(view, focus = false, updateHistory = true) {
  if (!Object.hasOwn(paths, view)) return;
  if (updateHistory && location.pathname !== paths[view]) history.pushState(null, '', paths[view]);
  currentView = view;
  for (const section of all('main > .view, .secondary-pages > .view')) {
    section.classList.toggle('active', section.id === 'view-' + view);
  }
  for (const nav of all('.nav')) {
    const active = nav.dataset.view === view;
    nav.classList.toggle('active', active);
    if (active) nav.setAttribute('aria-current', 'page');
    else nav.removeAttribute('aria-current');
  }
  $('page-title').hidden = !titles[view];
  $('task-progress').hidden = !['documents', 'summary'].includes(view);
  updatePageHeading(view);
  if (view === 'workspace' && !hasEnteredHome) {
    $('view-workspace').classList.add('landing-enter');
    hasEnteredHome = true;
  }
  syncFlight();
  syncAssistantPlacement();
  if (view === 'summary' && task) renderSummary();
  if (view === 'knowledge' && !knowledgeLoaded) loadKnowledge().catch(error => toast(error.message, true));
  if (view === 'evaluation' && !evaluationLoaded) loadEvaluation().catch(error => toast(error.message, true));
  if (focus) {
    window.scrollTo(0, 0);
    $(pageHeadings[view] || 'page-title').focus({preventScroll:true});
  }
}
function revealResult(id) {
  const result = $(id);
  const view = id === 'quote-output' ? 'rates' : 'tracking';
  if (result.hidden || view !== currentView) return;
  result.focus({preventScroll:true});
  result.scrollIntoView({block:'start'});
}

const scene = $('landing-scene');
const flight = scene.querySelector('animateMotion');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let hasEnteredHome = false, flightStarted = false, sceneVisible = true;
function syncFlight() {
  if (typeof flight.beginElement !== 'function') return;
  const play = currentView === 'workspace' && sceneVisible && !document.hidden && !reducedMotion.matches;
  scene.classList.toggle('flight-playing', play);
  if (play) {
    scene.unpauseAnimations();
    if (!flightStarted) {
      flight.beginElement();
      flightStarted = true;
    }
  } else {
    scene.pauseAnimations();
  }
}
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver(([entry]) => {
    sceneVisible = entry.isIntersecting;
    syncFlight();
  });
  observer.observe(scene);
}
reducedMotion.addEventListener('change', syncFlight);
document.addEventListener('visibilitychange', syncFlight);

const pointerMotion = window.matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)');
for (const button of all('.landing-action')) {
  const resetPosition = () => {
    button.style.removeProperty('--magnet-x');
    button.style.removeProperty('--magnet-y');
  };
  button.addEventListener('pointermove', event => {
    if (!pointerMotion.matches || event.pointerType !== 'mouse') return;
    const rect = button.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - .5;
    const y = (event.clientY - rect.top) / rect.height - .5;
    const ratio = 4 / Math.max(.5, Math.hypot(x, y));
    button.style.setProperty('--magnet-x', x * ratio + 'px');
    button.style.setProperty('--magnet-y', y * ratio + 'px');
  });
  button.addEventListener('pointerleave', resetPosition);
  button.addEventListener('blur', resetPosition);
  pointerMotion.addEventListener('change', resetPosition);
}
function syncDrawer() {
  const modal = smallScreen.matches && !assistant.hidden && !assistant.classList.contains('assistant-inline');
  for (const el of all('body > header, body > main, body > footer, .skip-link')) el.inert = modal;
  assistant.setAttribute('role', modal ? 'dialog' : 'complementary');
  if (modal) assistant.setAttribute('aria-modal', 'true');
  else assistant.removeAttribute('aria-modal');
  for (const button of all('[data-ask]')) button.setAttribute('aria-expanded', String(!assistant.hidden));
}
function syncAssistantPlacement() {
  const inline = currentView === 'rates' && wideShipping.matches;
  const wasInline = assistant.classList.contains('assistant-inline');
  if (inline && !wasInline) {
    $('shipping-assistant').append(assistant);
    document.body.classList.remove('drawer-open');
  } else if (!inline && wasInline) {
    document.body.append(assistant);
  }
  assistant.classList.toggle('assistant-inline', inline);
  assistant.hidden = inline ? inlineCollapsed : !document.body.classList.contains('drawer-open');
  $('shipping-ask').hidden = inline && !inlineCollapsed;
  renderAssistantShipment();
  syncDrawer();
}
function openAssistant(trigger) {
  if (!assistant.hidden) { $('chat-message').focus(); return; }
  drawerTrigger = trigger;
  if (assistant.classList.contains('assistant-inline')) inlineCollapsed = false;
  else document.body.classList.add('drawer-open');
  syncAssistantPlacement();
  $('messages').scrollTop = $('messages').scrollHeight;
  $('chat-message').focus({preventScroll:true});
}
function closeAssistant() {
  const inline = assistant.classList.contains('assistant-inline');
  if (inline) inlineCollapsed = true;
  else document.body.classList.remove('drawer-open');
  syncAssistantPlacement();
  if (drawerTrigger?.offsetParent) drawerTrigger.focus({preventScroll:true});
  else if (inline) $('shipping-ask').focus({preventScroll:true});
  else $('main').focus({preventScroll:true});
  drawerTrigger = null;
}
smallScreen.addEventListener('change', syncDrawer);
wideShipping.addEventListener('change', syncAssistantPlacement);
function renderAssistantShipment() {
  const panel = $('assistant-shipment');
  panel.hidden = currentView !== 'rates' || !task;
  if (panel.hidden) return;
  const field = formValues('rates');
  const dimensions = [field.length_cm, field.width_cm, field.height_cm];
  const values = [
    [tr('从', 'From'), [tr('中国大陆','Mainland China'), field.origin_province].filter(Boolean).join(' · ')],
    [tr('到', 'To'), [tr('美国','United States'), field.destination_city, field.destination_zip].filter(Boolean).join(' · ')],
    [tr('物品内容','Contents'), field.goods],
    [tr('重量','Weight'), field.weight_kg == null ? '' : field.weight_kg + ' kg'],
    [tr('尺寸','Dimensions'), dimensions.every(value => value != null) ? dimensions.join(' × ') + ' cm' : '']
  ];
  $('assistant-shipment-values').innerHTML = values.map(([label, value]) =>
    '<dt>' + label + '</dt><dd>' + esc(value || '—') + '</dd>').join('');
}
function refs(rows) {
  return rows?.length ? '<details class="references"><summary>查看依据（' + rows.length + '）</summary><div class="source-chips">' + rows.map(d => '<a target="_blank" rel="noopener noreferrer" href="' + esc(d.source_url) + '">' + esc(d.title || d.id) + (d.page ? ' · p.' + esc(d.page) : '') + ' ↗</a>').join('') + '</div></details>' : '';
}
function renderMessages() {
  const messages = task.messages || [], previousScroll = $('messages').scrollTop;
  const key = task.id + ':' + messages.length;
  $('quick-questions').hidden = messages.length > 0;
  $('messages').innerHTML = messages.length ? messages.map(m => {

    const changes = m.changes?.length ? '<div class="change-box">' + tr('已更新：', 'Updated: ') + m.changes.map(c =>
      esc(fieldName(c.field, c.label)) + ' ' + esc(c.before ?? '—') + ' → ' + esc(c.after ?? '—')
    ).join(' · ') + ' <button type="button" class="text-button" data-form-updates>' +
      tr('查看表单', 'View form') + ' →</button></div>' : '';
    const scenario = m.scenario?.differences?.length ? '<div class="scenario-box"><b>情景比较</b>' + m.scenario.differences.map(d => '<div>' + esc(d.service) + '：¥' + money(d.after) + '（' + (d.delta < 0 ? '减少 ' : '增加 ') + '¥' + money(Math.abs(d.delta)) + '）</div>').join('') + '</div>' : '';
    const trace = m.trace?.length ? '<details class="trace"><summary>处理记录（' + m.trace.length + '步）</summary>' + m.trace.map(t => '<p>' + esc(({update_shipment:'更新需求',estimate_rates:'计算参考费用',search_rules:'检索资料',check_documents:'核对文件',track_demo:'读取官方示例',estimate_scenario:'试算方案'})[t.tool] || t.tool) + ' · ' + esc(t.duration_ms) + ' ms</p>').join('') + '</details>' : '';
    const connection = m.role === 'assistant' && (m.model_error || m.connection_required) ? '<div class="message-connection">' + (m.model_error ? '<span>AI 连接未成功：' + esc(m.model_error) + '</span>' : '') + '<button class="text-button" type="button" data-model-settings>' + (m.model_error ? '检查 AI 设置' : '启用 AI 对话') + '</button></div>' : '';
    return '<div class="message ' + (m.role === 'user' ? 'user' : '') + '"><div class="message-body"><div class="message-text">' + esc(m.text) + '</div>' + connection + changes + scenario + refs(m.citations) + trace + '</div></div>';
  }).join('') : '<div class="message"><div class="message-body"><div class="message-text">' + tr('你打算从哪儿寄到哪儿？', 'Where are you shipping from and to?') + '</div></div></div>';
  const container = $('messages'), latest = container.lastElementChild;
  // Start a new answer where its text begins, including on short screens.
  container.scrollTop = key !== lastMessageKey && latest
    ? container.scrollTop + latest.getBoundingClientRect().top - container.getBoundingClientRect().top - 10
    : previousScroll;
  lastMessageKey = key;
}
function renderDraftStatus() {
  if (!task) return;
  $('discard-rates').hidden = !dirty('rates');
  for (const kind of Object.keys(forms)) {
    const element = $(kind === 'rates' ? 'rate-draft-status' : 'document-draft-status');
    if (!drafts[kind]) { element.textContent = ''; continue; }
    const merged = D.mergeDraft(drafts[kind].base, drafts[kind].values, savedValues(kind));

    const conflict = merged.conflicts.map(key => fieldName(key)).join(', ');
    element.textContent = merged.conflicts.length
      ? tr('请核对冲突字段：', 'Review conflicting fields: ') + conflict
      : storageAvailable ? tr('草稿已保留', 'Draft saved locally') : tr('草稿尚未保存', 'Draft not saved');
  }
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
const englishFields = {
  origin_province:'Origin', destination_country:'Destination country', destination_city:'City',
  destination_state:'State', destination_zip:'ZIP code', goods:'Contents', weight_kg:'Weight',
  length_cm:'Length', width_cm:'Width', height_cm:'Height', budget_cny:'Budget', deadline:'Arrival date',
  residential:'Address type', oda_tier:'Remote area tier', fuel_percent:'Fuel surcharge', items:'Items',
  sender_name:'Sender name', sender_address:'Sender address', sender_phone:'Sender phone',
  recipient_name:'Recipient name', recipient_address:'Recipient address', recipient_phone:'Recipient phone',
  currency:'Currency', country_of_origin:'Country of origin', invoice_total:'Invoice total'
};
function fieldName(key, fallback) {
  return tr(fallback || fieldLabels[key], englishFields[key]) || fallback || fieldLabels[key] || key;
}
function serviceName(code, fallback = code) {
  return tr(serviceNames[code], {IE:'International Economy', IP:'International Priority', IPE:'International Priority Express'}[code]) || fallback;
}
function pendingCost(label) {
  if (language !== 'en') return label;
  return {
    '税费、清关服务费及其他特殊费用':'Duties, taxes and clearance fees',
    '取件偏远地区资格':'Remote pickup surcharge',
    '账户价格资格与当前服务覆盖':'Account eligibility and service coverage',
    '住宅地址属性':'Residential address classification',
    '派送偏远地区档位及住宅费适用性':'Remote area and residential delivery surcharges',
    '当期燃油附加费':'Current fuel surcharge'
  }[label] || (label.includes('的时效要求') ? 'Delivery by ' + (label.match(/\d{4}-\d{2}-\d{2}/)?.[0] || 'the requested date') : label);
}
function costName(component) {
  if (language !== 'en') return component.label;
  if (component.source === 'inbound') return 'US inbound processing fee';
  if (component.source === 'fuel') return 'Fuel scenario (' + (component.label.match(/[\d.]+%/)?.[0] || '') + ')';
  if (component.source === 'remote') return component.label.includes('住宅')
    ? 'US residential delivery' : 'Remote delivery surcharge (' + (component.label.match(/ [ABC]/)?.[0]?.trim() || '') + ')';
  return 'Published base charge';
}
function renderQuote() {
  const quote = task.quote;
  showActiveResults();
  if (!quote) { $('quote-output').replaceChildren(); return; }
  const unsaved = dirty('rates') ? '<p class="draft-status">' +
    tr('表单已修改。重新比较后可选择方案。', 'Shipment edited. Compare rates again to select a service.') + '</p>' : '';
  const heading = '<div class="result-heading"><h2>' + tr('参考运费', 'Reference rates') + '</h2>' +
    (quote.status === 'estimated' ? '<p>' + tr('人民币 · 已知费用小计', 'CNY · Known charges only') + '</p>' : '') + '</div>';
  if (quote.status !== 'estimated') {
    const issue = language === 'zh' ? quote.message : quote.missing?.length
      ? 'Required: ' + quote.missing.map(key => fieldName(key)).join(', ')
      : quote.status === 'outside_scope' ? 'This shipment falls outside the published rate coverage.' : 'Confirm eligibility with the carrier before quoting.';
    $('quote-output').innerHTML = heading + unsaved + '<p class="form-error">' + esc(issue) + '</p>';
    return;
  }
  const weights = [
    [tr('实际重量', 'Actual weight'), quote.actual_kg],
    [tr('体积重量', 'Dimensional weight'), quote.volumetric_kg],
    [tr('计费重量', 'Billable weight'), quote.billable_kg]
  ].map(([label, value]) => '<span>' + label + '<strong>' + esc(value) + ' kg</strong></span>').join('');
  const options = quote.options.map(option => {
    const selected = task.selected_service?.service === option.service;
    const selectLabel = selected ? tr('已选 ✓', 'Selected ✓') : tr('选择方案', 'Select service');
    const costs = option.components.map(component => '<div class="cost-row"><span>' + esc(costName(component)) +
      '</span><strong>¥' + money(component.amount) + '</strong></div>').join('');
    return '<article class="quote-row' + (selected ? ' selected' : '') + '"><div class="quote-main"><h3 class="service-name">' +
      esc(serviceName(option.service, option.name)) + '</h3><div class="price">¥' + money(option.known_subtotal) + '</div>' +
      '<button type="button" class="button secondary" data-select="' + esc(option.service) + '" data-mutation' +
      (dirty('rates') ? ' disabled' : '') + '>' + selectLabel + '</button></div>' +
      '<details class="advanced"><summary>' + tr('费用明细与来源', 'Breakdown and source') + '</summary>' + costs +
      (option.budget_status === 'over' ? '<p class="form-error">' + tr('已知费用超出预算', 'Known charges exceed budget') + '</p>' : '') +
      '<a target="_blank" rel="noopener" href="' + esc(option.source_url) + '">' +
      tr('公开费率表 · 第 ', 'Published rate sheet · p. ') + esc(option.source_page) + ' ↗</a></details></article>';
  }).join('');
  $('quote-output').innerHTML = heading + unsaved + '<div class="weight-summary">' + weights + '</div>' +
    '<div class="quote-list">' + options + '</div><details class="advanced pending-rates"><summary>' +
    tr('待确认费用与适用范围', 'Charges to confirm and rate coverage') + '</summary><ul>' +
    quote.pending.map(item => '<li>' + esc(pendingCost(item)) + '</li>').join('') + '</ul><p>' +
    tr('适用于广东与福建以外中国大陆寄往美国的单件自备包装。账户资格、地址覆盖和送达时效需向承运人核对。费率生效日 ',
      'Rates cover a single parcel in your own packaging from mainland China (excluding Guangdong and Fujian) to the US. Confirm eligibility, coverage and transit time with the carrier. Rates effective ') +
    esc(quote.effective_from) + '.</p></details>';
}
const trackingMilestones = {
  received:['已揽收','Parcel received'], customs_clearance:['清关中','Customs clearance'],
  delivered:['已送达','Delivered'], in_transit:['运输中','In transit'], pending:['等待更新','Pending'],
  out_for_delivery:['正在派送','Out for delivery'], available_for_pickup:['可取件','Ready for pickup'],
  info_received:['已收到运单信息','Label created'], exception:['运输异常','Shipment exception'],
  failed_attempt:['派送未成功','Delivery attempt failed'], failed_delivery:['派送未成功','Delivery failed'],
  return_to_sender:['退回寄件人','Returning to sender'], expired:['查询已过期','Tracking expired'], delayed:['运输延误','Delayed']
};
function trackingStatus(status) {
  return trackingMilestones[status] ? tr(...trackingMilestones[status]) : status || tr('等待更新', 'Awaiting update');
}
function countryName(code) {
  if (!code) return '';
  return /^[A-Z]{2}$/i.test(code) ? new Intl.DisplayNames([tr('zh-CN', 'en')], {type:'region'}).of(code.toUpperCase()) : code;
}
function eventLocation(location) {
  if (typeof location === 'string') return location;
  if (!location) return '';
  const parts = [location.city, location.state || location.subdivision, countryName(location.countryCode || location.country)];
  return [...new Set(parts.filter(value => typeof value === 'string' && value))].join(', ');
}
function transportIcon(service, x, y) {
  const aircraft = /flight|air freight|air cargo|空运/i.test(service || '');
  const vessel = /ocean|sea freight|vessel|海运/i.test(service || '');
  if (!aircraft && !vessel) return '';
  const path = aircraft ? 'M0 9V4l-8-4v-2l8 2v-6a1.5 1.5 0 1 1 3 0v6l8-2v2L3 4v5l3 2v1l-4.5-1-4.5 1v-1Z'
    : 'M-9 0h18l-3 5H-6Zm4-4h10v4H-5Zm2-3h6v3M-9 8q3 2 6 0 3-2 6 0 3 2 6 0';
  return '<g transform="translate(' + x + ' ' + y + ')"><circle r="15" fill="#fffaf8"/><path d="' +
    path + '" fill="none" stroke="#885968" stroke-width="1.35" stroke-linejoin="round"/></g>';
}
const previewTracking = {
  tracking_number:'DEMO-2048', status:'in_transit', data_type:'local_visual_demo',
  origin_country:'US', destination_country:'CN',
  events:[
    {statusMilestone:'received', occurrenceDatetime:'2025-01-10T09:24:00-05:00', description:['纽约仓库已接收包裹','Parcel received at the New York facility']},
    {statusMilestone:'in_transit', occurrenceDatetime:'2025-01-12T16:30:00-05:00', description:['包裹已离开纽约，前往上海','Parcel departed New York for Shanghai']},
    {statusMilestone:'customs_clearance', pending:true},
    {statusMilestone:'out_for_delivery', pending:true}
  ]
};
function renderRouteMap(tracking) {
  const preview = tracking.data_type === 'local_visual_demo';
  const official = tracking.data_type === 'official_synthetic_sample';
  // Country-only markers are approximate and never derived from the shipping form.
  const countryPoints = {CN:[104,35], US:[-99,39], CA:[-106,54], MX:[-102,24], GB:[-2,54], FR:[2,46],
    DE:[10,51], JP:[138,37], AU:[134,-24], KR:[128,36], SG:[104,1], HK:[114,22], IN:[79,23]};
  const countryPoint = code => countryPoints[code?.toUpperCase?.()];
  let first = countryPoint(tracking.origin_country), last = countryPoint(tracking.destination_country);
  let labels = [countryName(tracking.origin_country), countryName(tracking.destination_country)];
  let height = 302, asset = 'world-land', box = '0 0 756 302';
  let project = ([lon, lat]) => [((lon + 382) % 360) * 2.1, (84 - lat) * 302 / 144];
  if (preview) {
    first = [-74.006,40.713]; last = [121.474,31.230];
    labels = [tr('纽约','New York'), tr('上海','Shanghai')];
    box = '186 24 513 222';
  } else if (official) {
    first = [2.518,49.003]; last = [2.352,48.857];
    labels = [tr('鲁瓦西', 'Roissy-en-France'), tr('巴黎', 'Paris')];
    height = 304; asset = 'france-land'; box = '0 0 756 304';
    project = ([lon, lat]) => [(lon + 6) * 756 / 16, (52 - lat) * 304 / 10];
  } else if ([tracking.origin_country, tracking.destination_country].sort().join('-') === 'CN-US') {
    box = '155 14 577 247';
  }
  if (!first || !last || (!official && !preview && tracking.origin_country === tracking.destination_country)) return '';
  const [x1,y1] = project(first).map(Math.round), [x2,y2] = project(last).map(Math.round);
  const curve = official ? 27 : Math.min(67, 22 + Math.abs(x2 - x1) / 13);
  const mx = Math.round((x1 + x2) / 2), my = Math.round((y1 + y2) / 2 - curve);
  const marker = (x,y) => '<g transform="translate(' + x + ' ' + y + ')"><path d="M0 3c-1-2-7-8-7-12a7 7 0 0 1 14 0c0 4-6 10-7 12Z" fill="#a65363" stroke="#fff" stroke-width="1.2"/><circle cx="0" cy="-9" r="2.2" fill="white"/></g>';
  const label = (x,y,value,anchor) => '<text x="' + x + '" y="' + y + '" text-anchor="' + anchor +
    '" fill="#513235" font-size="' + (preview ? 15 : 17) + '" font-weight="700" paint-order="stroke" stroke="#f8f5ed" stroke-width="4">' + esc(value) + '</text>';
  const caption = preview ? tr('示意路线 · 非实时定位', 'Illustrative route · No live location')
    : official ? tr('示例事件地点 · 路线为示意', 'Sample scan locations · Illustrative route')
    : tr('国家位置为近似标记 · 路线为示意，无实时定位', 'Approximate country markers · Illustrative route');
  const plane = preview ? '<use href="#landing-plane-symbol" transform="translate(' + mx + ' ' +
    (Math.round((my + (y1 + y2) / 2) / 2) - 12) + ') rotate(180) scale(.61)" fill="#f9f7f1" stroke="#a65363" stroke-width="2"/>' :
    transportIcon(tracking.service, mx, Math.round((my + (y1 + y2) / 2) / 2));
  return '<figure class="route-map"><svg role="img" aria-label="' + esc(labels.join(' → ') + ' · ' + caption) +
    '" viewBox="' + box + '"><image href="/' + asset + '.svg" width="756" height="' + height + '"/>' +
    '<path d="M' + x1 + ' ' + y1 + ' Q' + mx + ' ' + my + ' ' + x2 + ' ' + y2 +
    '" fill="none" stroke="#af6576" stroke-width="1.8" stroke-dasharray="4 4"/>' +
    marker(x1,y1) + marker(x2,y2) +
    label(x1 + (official ? 13 : 0),y1 + (official ? -13 : 16),labels[0],official ? 'start' : 'middle') +
    label(x2 - (official ? 12 : 0),y2 + (official ? 18 : 17),labels[1],official ? 'end' : 'middle') +
    plane + '</svg><figcaption>' + caption + '</figcaption></figure>';
}
function renderTracking() {
  const tracking = sampleTracking || task.tracking || previewTracking;
  showActiveResults();
  const preview = tracking.data_type === 'local_visual_demo';
  const official = tracking.data_type === 'official_synthetic_sample';
  const events = tracking.events || [];
  const latestStatus = tracking.status || events[0]?.statusMilestone;
  const caption = trackingStatus(latestStatus);
  const officialLabel = official ? tr('官方模拟示例', 'Official simulated sample') : 'Ship24';
  const issues = ['exception','failed_attempt','failed_delivery','return_to_sender','expired','delayed'];
  const scanIssue = !preview && !official && latestStatus !== 'delivered' && issues.includes(events[0]?.statusMilestone)
    ? '<p class="tracking-alert">' + esc(trackingStatus(events[0].statusMilestone)) + '</p>' : '';
  const eta = formatDeliveryDate(tracking.estimated_delivery) || tr('待确认', 'Pending');
  const route = preview ? tr('纽约 → 上海', 'New York → Shanghai') : [
    countryName(tracking.origin_country),
    [tracking.destination_city, countryName(tracking.destination_country)].filter(Boolean).join(', ')
  ].filter(Boolean).join(' → ');
  const service = preview ? tr('国际快递', 'International express') : tracking.service;
  const details = [service, route].filter(Boolean).map(esc).join(' · ');
  const timeline = events.map(event => {
    const title = event.statusMilestone ? trackingStatus(event.statusMilestone) : event.status;
    const date = activityDate(event.occurrenceDatetime, {dateStyle:'medium', timeStyle:'short'});
    const location = eventLocation(event.location);
    const description = event.description ? tr(...event.description) : event.status !== title ? event.status : '';
    return '<li class="timeline-event' + (event.pending ? ' pending' : '') + '"><h3>' + esc(title || tr('物流更新','Tracking update')) +
      '</h3><div class="event-meta">' + (date ? '<time datetime="' + esc(event.occurrenceDatetime) + '">' + esc(date) + '</time>' : '') +
      (location ? '<p>' + esc(location) + '</p>' : '') +
      (event.pending ? '<p>' + tr('待更新','Awaiting update') + '</p>' : '') + '</div>' +
      (description ? '<p class="event-description">' + esc(description) + '</p>' : '') + '</li>';
  }).join('');
  const map = renderRouteMap(tracking) || '<p class="tracking-map-empty">' +
    tr('暂无可用于绘制路线的地点。', 'Route locations are unavailable.') + '</p>';
  const sourceURL = typeof tracking.source_url === 'string' && tracking.source_url.startsWith('https://') ? tracking.source_url : '';
  const checked = activityDate(tracking.queried_at, {dateStyle:'medium', timeStyle:'short'});
  const source = '<div class="tracking-source"><span class="pill">' +
    (preview ? tr('演示数据', 'Demo data') : officialLabel) + '</span><span>' + esc(tracking.tracking_number) +
    '</span>' + (checked ? '<span>' + tr('查询时间 ', 'Last checked ') + esc(checked) + '</span>' : '') +
    (sourceURL ? '<a target="_blank" rel="noopener" href="' + esc(sourceURL) + '">' + tr('状态说明','Status guide') + ' ↗</a>' : '') + '</div>';
  $('tracking-output').innerHTML = '<div class="tracking-workspace"><div class="tracking-map-column">' + map +
    '<div class="tracking-strip"><strong>' + esc(caption) + '</strong><span>' + tr('预计送达：','Estimated delivery: ') + esc(eta) +
    '</span></div></div><div class="tracking-detail"><div class="tracking-heading"><h2>' + tr('当前状态：','Current status: ') +
    '<strong>' + esc(caption) + '</strong></h2><button type="button" data-ask class="text-button tracking-ask" aria-controls="assistant-drawer" aria-expanded="' +
    String(!assistant.hidden) + '"><svg class="line-icon" aria-hidden="true"><use href="#icon-send"/></svg>' + tr('询问 AI','Ask AI') +
    '</button></div>' + (details ? '<p class="tracking-service">' + details + '</p>' : '') + scanIssue +
    (timeline ? '<ol class="timeline">' + timeline + '</ol>' : '<p>' + tr('暂无运输事件。', 'No scans available yet.') + '</p>') + source + '</div></div>';
}
function renderProgress() {
  const progress = task.progress;
  const current = dirty('rates') ? 0 : task.selected_service ? 2 : task.quote?.status === 'estimated' ? 1 : 0;
  [...$('shipping-steps').children].forEach((step, index) => {
    step.classList.toggle('current', index === current);
    step.classList.toggle('complete', index < current);
    if (index === current) step.setAttribute('aria-current', 'step');
    else step.removeAttribute('aria-current');
  });
  $('step-quotes').disabled = !task.quote;
  if (!progress) { $('task-progress').replaceChildren(); return; }
  $('task-progress').innerHTML = progress.steps.map(step =>
    '<button class="step ' + esc(step.status) + '" data-go="' + progressSteps[step.id][2] + '"' +
    (step.status === 'current' ? ' aria-current="step"' : '') + '>' +
    (step.status === 'complete' ? '✓ ' : '') + tr(...progressSteps[step.id]) + '</button>').join('');
}
function renderSummary() {
  const {selected_service:selected, progress, fields:f} = task;
  const pendingDrafts = dirty('rates') || dirty('documents');
  const route = [f.origin_province || tr('待填写', 'Origin needed'), f.destination_city || tr('美国', 'United States')].join(' → ');
  const size = [f.length_cm, f.width_cm, f.height_cm].every(Boolean)
    ? [f.length_cm, f.width_cm, f.height_cm].join(' × ') + ' cm' : '';
  const facts = [f.goods, f.weight_kg ? f.weight_kg + ' kg' : '', size].filter(Boolean).map(esc).join(' · ');
  const progressItems = (progress?.steps || []).filter(step => step.id !== 'summary').map(step =>
    '<li>' + (step.status === 'complete' ? '✓ ' : '○ ') + tr(...progressSteps[step.id]) +
    (language === 'zh' ? ' · ' + esc(step.description) : '') + '</li>').join('');
  const pending = task.quote?.pending || [
    tr('服务覆盖、适用价格和最终费用','Service coverage and final charges'),
    tr('清关文件及送达安排','Customs paperwork and delivery arrangements')
  ];
  const draft = pendingDrafts ? '<p class="draft-status">' +
    tr('清单仅显示已保存内容。请先保存草稿再打印。','This checklist shows saved details. Save your drafts before printing.') + '</p>' : '';
  $('summary-output').innerHTML = draft + '<article class="card"><div class="card-head"><h2>' +
    (progress?.ready_for_summary && !pendingDrafts ? tr('寄件信息已整理','Shipment details ready') :
      tr('仍需补齐信息','Details to complete')) + '</h2>' +
    '<button class="button secondary" id="print-summary" data-mutation>' +
    tr('打印清单','Print checklist') + '</button></div>' +
    (task.is_demo ? '<span class="pill amber">' + tr('示例任务','Sample shipment') + '</span>' : '') +
    '<div class="summary-grid"><div><h3>' + tr('包裹与路线','Parcel and route') +
    '</h3><p>' + esc(route) + (f.destination_zip ? ' ' + esc(f.destination_zip) : '') +
    (facts ? '<br>' + facts : '') + '</p><h3>' + tr('参考方案','Selected service') + '</h3>' +
    (selected ? '<p>' + esc(serviceName(selected.service, selected.name)) + ' · ¥' +
      money(selected.known_subtotal) + ' CNY</p>' :
      '<button class="text-button" data-go="rates">' + tr('比较并选择方案','Compare rates') + ' →</button>') +
    '</div><div><h3>' + tr('准备进度','Preparation') + '</h3><ul>' + progressItems +
    '</ul><h3>' + tr('向承运人核验','Confirm with the carrier') + '</h3><ul>' +
    pending.map(item => '<li>' + esc(pendingCost(item)) + '</li>').join('') + '</ul></div></div></article>';
}
function render() {
  if (!task) return;
  storageSet('parcel-task-id', task.id);

  $('task-short').hidden = !task.is_demo;
  $('task-short').textContent = tr('示例任务', 'Sample shipment');
  const f = task.fields;

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

  $('document-shipment').textContent = f.goods ? f.goods + (f.weight_kg ? ' · ' + f.weight_kg + ' kg' : '') : '';
  renderMessages(); renderDraftStatus(); renderQuote(); renderChecks(); renderTracking(); renderProgress(); renderSummary();
  renderAssistantShipment();
  if (busy) lockNewControls();
}
function activityDate(value, options = {month:'short', day:'numeric'}) {
  if (!value || Number.isNaN(new Date(value).valueOf())) return '';
  return new Date(value).toLocaleString(tr('zh-CN', 'en-US'), options);
}
function formatDeliveryDate(value) {
  if (!value) return '';
  const options = /^\d{4}-\d{2}-\d{2}$/.test(value) ? {dateStyle:'medium', timeZone:'UTC'} : {dateStyle:'medium'};
  return activityDate(value, options) || value;
}
function taskLabel(row) {
  const route = [row.origin, row.city || row.destination_zip].filter(Boolean).join(' → ');
  return [row.is_demo ? tr('示例任务', 'Sample shipment') : '', row.goods, route,
    row.weight_kg ? row.weight_kg + ' kg' : ''].filter(Boolean).join(' · ') ||
    tr('未命名寄件', 'Untitled shipment');
}
function renderHistory() {
  $('task-history').innerHTML = historyRows.map(row => '<option value="' + esc(row.id) + '">' + esc(taskLabel(row)) + '</option>').join('');
  $('task-history').value = task.id;
  const entries = historyRows.filter(row => !row.is_demo).flatMap(row => {
    const entries = [];
    if (row.origin || row.goods || row.selected_service) entries.push({title:taskLabel(row), date:row.updated_at, id:row.id, view:'rates'});
    if (row.tracking?.number) entries.push({title:trackingStatus(row.tracking.status) + ' · ' + row.tracking.number, date:row.tracking.queried_at, id:row.id, view:'tracking'});
    return entries;
  }).sort((a, b) => (Date.parse(b.date) || 0) - (Date.parse(a.date) || 0)).slice(0, 3);
  $('recent-activity').innerHTML = entries.length ? entries.map(entry =>
    '<button class="activity-entry" type="button" data-history-id="' + esc(entry.id) + '" data-history-view="' + entry.view + '" data-mutation>' +
    '<span><strong>' + esc(entry.title) + '</strong><time>' + esc(activityDate(entry.date)) +
    '</time></span><span aria-hidden="true">→</span></button>').join('') :
    '<p class="activity-empty">' + tr('还没有寄件或追踪记录。', 'No shipments or tracking activity yet.') + '</p>';
  if (busy) lockNewControls();
}
async function refreshHistory() {
  historyRows = (await api('/api/tasks')).tasks;
  renderHistory();
}
function updateCurrentHistory() {
  const f = task.fields, tracking = task.tracking;
  const row = {id:task.id, origin:f.origin_province, city:f.destination_city, destination_zip:f.destination_zip,
    goods:f.goods, weight_kg:f.weight_kg, updated_at:task.updated_at, is_demo:task.is_demo,
    selected_service:task.selected_service?.service,
    tracking:tracking?.data_type === 'live_api' ? {number:tracking.tracking_number, status:tracking.status, queried_at:tracking.queried_at} : null};
  historyRows = [row, ...historyRows.filter(old => old.id !== task.id)];
  renderHistory();
}
async function switchTo(next) {
  if (task) storageSet('parcel-chat-draft:' + task.id, $('chat-message').value);
  task = next; restoreDrafts(); lastMessageKey = '';
  sampleTracking = null;
  $('chat-message').value = storageGet('parcel-chat-draft:' + task.id) || '';
  $('tracking-number').value = task.tracking?.data_type === 'live_api' ? task.tracking.tracking_number : '';
  updateTrackingConsent();
  $('tracking-live').checked = false;
  $('rate-options').open = false;
  for (const kind of ['rates','documents','tracking']) formError(kind, '');
  render(); await refreshHistory();
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

for (const link of all('[data-view]')) {
  link.addEventListener('click', event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    go(link.dataset.view, true);
  });
}
window.addEventListener('popstate', () => go(viewForPath(), true, false));
go(viewForPath(), false, false);
$('close-assistant').onclick = closeAssistant;
document.addEventListener('keydown', event => {
  if ($('assistant-drawer').hidden) return;
  if (event.key === 'Escape' && (!assistant.classList.contains('assistant-inline') || assistant.contains(document.activeElement))) { closeAssistant(); return; }
  if (event.key !== 'Tab' || !smallScreen.matches) return;
  const focusable = [...$('assistant-drawer').querySelectorAll('button, a[href], input, select, textarea, summary')]
    .filter(element => !element.disabled && element.getClientRects().length);
  const first = focusable[0], last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});

document.addEventListener('click', event => {
  const ask = event.target.closest('[data-ask]');
  if (ask) { openAssistant(ask); return; }
  if (event.target.closest('[data-model-settings]')) { openModelSettings(); return; }
  if (event.target.closest('[data-form-updates]')) {
    if (smallScreen.matches) closeAssistant();
    $('rate-options').open = true;
    go('rates', true);
    return;
  }
  const entry = event.target.closest('[data-history-id]');
  if (entry) {
    run(tr('正在打开记录…', 'Opening record…'), async () => {
      if (entry.dataset.historyId !== task.id) await switchTo(await api('/api/task?id=' + encodeURIComponent(entry.dataset.historyId)));
      go(entry.dataset.historyView, true);
      if (entry.dataset.historyView === 'tracking') {
        sampleTracking = null;
        renderTracking();
        revealResult('tracking-output');
      }
    });
    return;
  }
  const goButton = event.target.closest('[data-go]');
  if (goButton) { go(goButton.dataset.go, true); return; }
  const choose = event.target.closest('[data-select]');
  if (choose) run('正在保存参考方案…', async () => {
    if (dirty('rates')) throw new Error('请先保存包裹修改并重新估算。');
    await action('/api/select', {service:choose.dataset.select}); go('documents', true);
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
all('[data-message]').forEach(button => {
  button.onclick = () => {
    $('chat-message').value = tr(button.dataset.message, button.dataset.messageEn);
    $('chat-message').dispatchEvent(new Event('input'));
    $('chat-message').focus();
  };
});
$('rate-form').onsubmit = event => { event.preventDefault(); run(tr('正在比较运费…', 'Comparing rates…'), async () => { await action('/api/quote', {fields:fieldsForSave('rates')}, 'rates'); revealResult('quote-output'); }, 'rates'); };
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
$('tracking-form').onsubmit = event => {
  event.preventDefault();
  if ($('tracking-number').value.trim().toUpperCase() === previewTracking.tracking_number) {
    showTrackingPreview();
    return;
  }
  run(tr('正在向 Ship24 查询…', 'Checking with Ship24…'), async () => {
    if (!$('tracking-live').checked) throw new Error(tr('请先同意通过 Ship24 查询。', 'Allow the Ship24 lookup first.'));
    const number = $('tracking-number').value.trim();
    if (number === sample) throw new Error(tr('请点击“查看官方物流示例”。', 'Use the official sample link below.'));
    await action('/api/track', {number, allow_live:true});
    sampleTracking = null;
    renderTracking();
    revealResult('tracking-output');
  }, 'tracking');
};
$('step-quotes').onclick = () => revealResult('quote-output');
function showTrackingPreview() {
  if (!task) return;
  formError('tracking', '');
  sampleTracking = previewTracking;
  renderTracking();
  revealResult('tracking-output');
}
$('track-preview').onclick = showTrackingPreview;
$('tracking-number').addEventListener('input', updateTrackingConsent);
function updateTrackingConsent() {
  $('tracking-live').required = $('tracking-number').value.trim().toUpperCase() !== previewTracking.tracking_number;
}
$('track-demo').onclick = () => run(tr('正在加载示例…', 'Loading tracking sample…'), async () => {
  sampleTracking = await api('/api/track/sample');
  renderTracking();
  revealResult('tracking-output');
});
$('search-form').onsubmit = event => { event.preventDefault(); run('正在检索资料…', async () => { renderCards((await api('/api/search', {query:$('search-query').value, method:$('search-method').value})).results); knowledgeLoaded = true; }); };
$('new-task').onclick = () => run('正在新建寄件任务…', async () => { await switchTo(await api('/api/tasks', {})); go('rates', true); toast(tr('新寄件已创建', 'New shipment created')); });
$('task-history').onchange = () => run('正在载入已有任务…', async () => { const id = $('task-history').value; try { if (id !== task.id) await switchTo(await api('/api/task?id=' + encodeURIComponent(id))); go('rates', true); } catch (error) { $('task-history').value = task.id; throw error; } });
$('export-task').onclick = () => {
  const blob = new Blob([JSON.stringify(task, null, 2)], {type:'application/json'}), a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'parcel-task-' + task.id.slice(0,8) + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href),1000);
  if (dirty('rates') || dirty('documents')) toast('导出的是已保存任务；未保存的表单仍在本机草稿中。');
};
$('load-demo').onclick = () => run('正在创建独立示例任务…', async () => {
  await switchTo(await api('/api/tasks', {demo:true}));
  await action('/api/task', {fields:{origin_province:'Shanghai',destination_country:'US',destination_state:'CA',destination_city:'Los Angeles',destination_zip:'90001',goods:'Cotton T-shirts',weight_kg:10,length_cm:30,width_cm:20,height_cm:10,budget_cny:5000,oda_tier:'unknown',currency:'USD',country_of_origin:'CN',invoice_number:'DEMO-001',ship_date:new Date().toLocaleDateString('sv-SE'),sender_name:'Demo Sender',sender_address:'Example origin address · fictitious',sender_phone:'00000000000',recipient_name:'Demo Recipient',recipient_address:'Example destination address · fictitious',recipient_phone:'00000000000',invoice_total:50,items:[{description:'Cotton T-shirt',quantity:2,packing_quantity:2,unit_price:25}]}});
  await action('/api/quote');
  go('rates', true);
  revealResult('quote-output');
  toast(tr('示例寄件已载入', 'Sample shipment loaded'));
});

function renderModelSettings() {
  const configured = !!modelSettings?.configured;
  $('open-model-settings').textContent = configured ? tr('设置', 'Settings') : tr('连接 AI', 'Connect AI');
  $('model-name').value = modelSettings?.model || '';
  $('model-base-url').value = modelSettings?.base_url || 'https://api.openai.com/v1';
  $('model-api-style').value = modelSettings?.api_style || 'responses';
  $('model-key').required = !modelSettings?.has_api_key;
  $('model-key').placeholder = modelSettings?.has_api_key ? tr('留空保留现有密钥', 'Leave blank to keep your key') : tr('填写该服务的 API Key', 'Enter the provider’s API key');
  $('model-settings-status').textContent = '';
}
async function loadModelSettings() {
  modelSettings = await api('/api/model/settings');
  renderModelSettings();
}
function openModelSettings() {
  $('model-setup').hidden = false;
  $('model-name').focus();
}
$('open-model-settings').onclick = openModelSettings;
$('close-model-settings').onclick = () => {
  $('model-setup').hidden = true;
  $('open-model-settings').focus();
};
$('model-settings-form').onsubmit = event => {
  event.preventDefault();
  const error = $('model-settings-error'); error.hidden = true; error.textContent = '';
  const values = Object.fromEntries(new FormData($('model-settings-form')));
  run('正在保存 AI 设置…', async () => {
    try {
      await api('/api/model/settings', values);
      $('model-key').value = '';
      health = await api('/api/health'); await loadModelSettings();
      $('model-setup').hidden = true;
      $('chat-message').focus();
      toast(tr('设置已保存', 'Settings saved'));
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
  } catch (error) { $('messages').innerHTML = '<div class="form-error">' + esc(error.message) + ' <button class="text-button" onclick="location.reload()">重新连接</button></div>'; toast(error.message, true); }
})();
