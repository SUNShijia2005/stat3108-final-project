'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const D = require('../static/drafts.js');
let count = 0;
function test(name, run) {
  run();
  count += 1;
  process.stdout.write(`ok ${count} - ${name}\n`);
}

test('an ordinary edit produces only the changed field', () => {
  assert.deepEqual(D.changedFields({ weight: 10, zip: '90001' }, { weight: 8, zip: '90001' }), { weight: 8 });
});
test('unchanged form fields adopt newer server values', () => {
  const result = D.mergeDraft(
    { weight: 10, sender: 'Old name' },
    { weight: 10, sender: 'Draft name' },
    { weight: 8, sender: 'Old name', selected_service: null }
  );
  assert.deepEqual(result, {
    fields: { weight: 8, sender: 'Draft name' },
    patch: { sender: 'Draft name' },
    conflicts: []
  });
});
test('different changes to the same field report a conflict without losing the draft', () => {
  const result = D.mergeDraft({ weight: 10 }, { weight: 8 }, { weight: 12 });
  assert.deepEqual(result.conflicts, ['weight']);
  assert.equal(result.fields.weight, 8);
  assert.deepEqual(result.patch, { weight: 8 });
});
test('the same update in both places needs no second write', () => {
  assert.deepEqual(D.mergeDraft({ weight: 10 }, { weight: 8 }, { weight: 8 }), {
    fields: { weight: 8 }, patch: {}, conflicts: []
  });
});
test('explicit null clears are preserved in serialized patches', () => {
  assert.deepEqual(D.changedFields({ phone: '000000' }, { phone: null }), { phone: null });
  assert.deepEqual(D.changedFields({ phone: '000000' }, { phone: undefined }), { phone: null });
  assert.deepEqual(D.changedFields({}, { phone: null }), {});
});
test('a server-side clear is adopted when the local field was untouched', () => {
  assert.deepEqual(D.mergeDraft({ phone: '000000' }, { phone: '000000' }, {}), {
    fields: { phone: null }, patch: {}, conflicts: []
  });
});
test('missing keys in the form are excluded from merged output and patches', () => {
  const result = D.mergeDraft({ weight: 10, zip: '90001' }, { weight: 8 }, { weight: 10, zip: '10001' });
  assert.deepEqual(result.fields, { weight: 8 });
  assert.deepEqual(result.patch, { weight: 8 });
});
test('item-array edits are detected structurally and remain isolated from source values', () => {
  const base = { items: [{ description: 'Cotton shirt', quantity: 2, unit_price: 25 }] };
  const values = D.clone(base);
  values.items[0].quantity = 3;
  const result = D.mergeDraft(base, values, base);
  assert.equal(result.patch.items[0].quantity, 3);
  result.fields.items[0].quantity = 4;
  assert.equal(base.items[0].quantity, 2);
  assert.equal(values.items[0].quantity, 3);
  assert.equal(result.patch.items[0].quantity, 3);
});
test('concurrent item changes conflict rather than silently overwriting a line', () => {
  const result = D.mergeDraft({ items: [{ quantity: 2 }] }, { items: [{ quantity: 3 }] }, { items: [{ quantity: 4 }] });
  assert.deepEqual(result.conflicts, ['items']);
});
test('repeated server updates stay server-owned after a local edit and render', () => {
  const initial = { sender: 'Saved', total: 50 };
  const first = D.rebaseDraft(initial, { sender: 'Draft', total: 50 }, { sender: 'Saved', total: 60 });
  assert.deepEqual(first, {
    base: { sender: 'Saved', total: 60 }, values: { sender: 'Draft', total: 60 }, conflicts: []
  });
  const second = D.rebaseDraft(first.base, { ...first.values, sender: 'Edited again' }, { sender: 'Saved', total: 70 });
  assert.equal(second.values.total, 70);
  assert.deepEqual(second.conflicts, []);
  assert.deepEqual(D.changedFields(second.base, second.values), { sender: 'Edited again' });
});
test('rebasing preserves original bases for genuine conflicting local edits', () => {
  const first = D.rebaseDraft({ weight: 10 }, { weight: 8 }, { weight: 12 });
  assert.deepEqual(first, { base: { weight: 10 }, values: { weight: 8 }, conflicts: ['weight'] });
  const second = D.rebaseDraft(first.base, first.values, { weight: 13 });
  assert.deepEqual(second, { base: { weight: 10 }, values: { weight: 8 }, conflicts: ['weight'] });
});
test('a local value already saved by another update becomes a clean field', () => {
  const result = D.rebaseDraft({ weight: 10, phone: '000000' }, { weight: 8, phone: null }, { weight: 8, phone: null });
  assert.deepEqual(result.conflicts, []);
  assert.deepEqual(D.changedFields(result.base, result.values), {});
  assert.deepEqual(result.base, { weight: 8, phone: null });
});
test('object order is irrelevant but array order is retained', () => {
  assert.equal(D.equal({ a: 1, b: 2 }, { b: 2, a: 1 }), true);
  assert.equal(D.equal([{ a: 1 }, { a: 2 }], [{ a: 2 }, { a: 1 }]), false);
  assert.equal(D.equal(null, undefined), true);
  assert.equal(D.equal('', null), false);
  assert.equal(D.equal({ a: null }, {}), true);
});
test('valid storage records round-trip with no extra metadata', () => {
  const data = new Map();
  const storage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
  assert.equal(D.saveDraft(storage, 'task', { base: { weight: 10 }, values: { weight: 8 }, extra: true }), true);
  assert.deepEqual(D.loadDraft(storage, 'task'), { base: { weight: 10 }, values: { weight: 8 } });
  assert.equal(D.loadDraft(storage, 'unknown'), null);
});
test('malformed or invalid storage is ignored', () => {
  for (const raw of ['broken JSON', 'null', '[]', '{}', '{"base":[],"values":{}}', '{"base":{}}']) {
    assert.equal(D.loadDraft({ getItem: () => raw }, 'task'), null);
  }
});
test('storage denial and quota exhaustion do not throw', () => {
  const denied = { getItem() { throw new Error('Denied'); }, setItem() { throw new Error('Quota'); } };
  assert.equal(D.loadDraft(denied, 'task'), null);
  assert.equal(D.saveDraft(denied, 'task', { base: {}, values: {} }), false);
  assert.equal(D.saveDraft(denied, 'task', { base: [] }), false);
  const cyclic = { base: {}, values: {} }; cyclic.values.self = cyclic.values;
  assert.equal(D.saveDraft(denied, 'task', cyclic), false);
});
test('the same helper exposes a browser global without CommonJS', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/drafts.js'), 'utf8'), context);
  assert.equal(typeof context.ParcelDrafts.mergeDraft, 'function');
  assert.equal(context.ParcelDrafts.equal({ weight: 10 }, { weight: 10 }), true);
});
process.stdout.write(`${count} draft-state checks passed.\n`);
