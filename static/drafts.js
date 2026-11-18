(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ParcelDrafts = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function clone(value) {
    if (Array.isArray(value)) return value.map(clone);
    if (isRecord(value)) {
      return Object.fromEntries(Object.keys(value).map(key => [key, clone(value[key])]));
    }
    return value;
  }

  // A missing field and an explicit null both represent a cleared form field.
  function equal(a, b) {
    if (a == null && b == null) return true;
    if (Object.is(a, b)) return true;
    if (Array.isArray(a) || Array.isArray(b)) {
      return Array.isArray(a) && Array.isArray(b) && a.length === b.length &&
        a.every((value, index) => equal(value, b[index]));
    }
    if (isRecord(a) && isRecord(b)) {
      const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
      return [...keys].every(key => equal(a[key], b[key]));
    }
    return false;
  }

  function fieldValue(value) {
    return value == null ? null : clone(value);
  }

  function changedFields(base, values) {
    base = isRecord(base) ? base : {};
    values = isRecord(values) ? values : {};
    return Object.fromEntries(Object.keys(values)
      .filter(key => !equal(base[key], values[key]))
      .map(key => [key, fieldValue(values[key])]));
  }

  function mergeDraft(base, values, latest) {
    base = isRecord(base) ? base : {};
    values = isRecord(values) ? values : {};
    latest = isRecord(latest) ? latest : {};
    const fields = [];
    const patch = [];
    const conflicts = [];
    for (const key of Object.keys(values)) {
      const localChanged = !equal(values[key], base[key]);
      const serverChanged = !equal(latest[key], base[key]);
      const differsFromLatest = !equal(values[key], latest[key]);
      fields.push([key, fieldValue(localChanged ? values[key] : latest[key])]);
      if (localChanged && differsFromLatest) patch.push([key, fieldValue(values[key])]);
      if (localChanged && serverChanged && differsFromLatest) conflicts.push(key);
    }
    return { fields: Object.fromEntries(fields), patch: Object.fromEntries(patch), conflicts };
  }

  // Adopt server updates for untouched fields without turning them into local edits.
  function rebaseDraft(base, values, latest) {
    base = isRecord(base) ? base : {};
    values = isRecord(values) ? values : {};
    latest = isRecord(latest) ? latest : {};
    const merged = mergeDraft(base, values, latest);
    const nextBase = Object.fromEntries(Object.keys(values).map(key => {
      const unresolvedEdit = !equal(values[key], base[key]) && !equal(values[key], latest[key]);
      return [key, fieldValue(unresolvedEdit ? base[key] : latest[key])];
    }));
    return { base: nextBase, values: merged.fields, conflicts: merged.conflicts };
  }

  function validDraft(value) {
    return isRecord(value) && isRecord(value.base) && isRecord(value.values);
  }

  function loadDraft(storage, key) {
    try {
      const raw = storage.getItem(key);
      if (raw === null) return null;
      const record = JSON.parse(raw);
      return validDraft(record) ? { base: clone(record.base), values: clone(record.values) } : null;
    } catch (_) {
      return null;
    }
  }

  function saveDraft(storage, key, record) {
    if (!validDraft(record)) return false;
    try {
      const raw = JSON.stringify({ base: record.base, values: record.values });
      if (!validDraft(JSON.parse(raw))) return false;
      storage.setItem(key, raw);
      return true;
    } catch (_) {
      return false;
    }
  }

  return { clone, equal, changedFields, mergeDraft, rebaseDraft, loadDraft, saveDraft };
});
