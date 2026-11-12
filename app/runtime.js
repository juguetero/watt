/*
 * Watts & Kilos — runtime local para iPhone.
 *
 * Reemplaza el `window.claude` que entregaba Claude Artifacts:
 *   - use('db')        → base de datos local (IndexedDB) con la misma API estilo Firestore
 *   - use('sample')    → Claude vía API de Anthropic con tu propia API key (guardada solo en el teléfono)
 *   - use('downloads') → guardar/compartir archivos con la hoja de compartir de iOS
 *
 * Todo vive en el dispositivo. Nada se sube a ningún servidor salvo las consultas a Claude.
 */
(function () {
  'use strict';

  var DB_NAME = 'watts-kilos';
  var STORE = 'docs';
  var SDK_URL = 'https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@1.3.0/+esm';
  var LS = {
    key: 'wk.apiKey',
    model: 'wk.model',
    lastBackup: 'wk.lastBackup'
  };
  var DEFAULT_MODEL = 'claude-opus-5-5';

  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { if (v == null || v === '') localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }
  function clone(o) { return o == null ? o : JSON.parse(JSON.stringify(o)); }
  function err(code, msg) { var e = new Error(msg || code); e.code = code; return e; }

  // ------------------------------------------------------------------
  // Almacenamiento: IndexedDB con caché en memoria
  // ------------------------------------------------------------------
  var cache = {};          // { coleccion: { id: doc } }
  var listeners = [];      // { col, query, cb }
  var idbPromise = null;

  function openIdb() {
    if (idbPromise) return idbPromise;
    idbPromise = new Promise(function (resolve, reject) {
      if (!('indexedDB' in window)) { reject(err('unavailable')); return; }
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () { req.result.createObjectStore(STORE); };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(err('unavailable', String(req.error))); };
    }).then(function (idb) {
      return new Promise(function (resolve, reject) {
        var tx = idb.transaction(STORE, 'readonly');
        var st = tx.objectStore(STORE);
        var r = st.openCursor();
        r.onsuccess = function () {
          var c = r.result;
          if (c) {
            var k = String(c.key), i = k.indexOf('/');
            var col = k.slice(0, i), id = k.slice(i + 1);
            (cache[col] = cache[col] || {})[id] = c.value;
            c.continue();
          }
        };
        tx.oncomplete = function () { resolve(idb); };
        tx.onerror = function () { reject(err('unavailable', String(tx.error))); };
      });
    });
    return idbPromise;
  }

  function idbWrite(ops) { // ops: [{col,id,doc|null}]
    return openIdb().then(function (idb) {
      return new Promise(function (resolve, reject) {
        var tx = idb.transaction(STORE, 'readwrite');
        var st = tx.objectStore(STORE);
        ops.forEach(function (o) {
          if (o.doc == null) st.delete(o.col + '/' + o.id); else st.put(o.doc, o.col + '/' + o.id);
        });
        tx.oncomplete = function () { resolve(); };
        tx.onerror = tx.onabort = function () { reject(err('write_failed', String(tx.error))); };
      });
    });
  }

  function applyLocal(ops) {
    var touched = {};
    ops.forEach(function (o) {
      var c = cache[o.col] = cache[o.col] || {};
      if (o.doc == null) delete c[o.id]; else c[o.id] = clone(o.doc);
      touched[o.col] = true;
    });
    listeners.forEach(function (l) { if (touched[l.col]) fire(l); });
  }

  function snapshotOf(col, q) {
    var c = cache[col] || {};
    var ids = Object.keys(c);
    if (q.orderBy) {
      var f = q.orderBy.field, dir = q.orderBy.dir === 'desc' ? -1 : 1;
      ids.sort(function (a, b) {
        var x = c[a] && c[a][f], y = c[b] && c[b][f];
        if (x === y) return 0;
        if (x == null) return -1 * dir;
        if (y == null) return 1 * dir;
        return (x < y ? -1 : 1) * dir;
      });
    } else ids.sort();
    if (q.limit) ids = ids.slice(0, q.limit);
    var docs = ids.map(function (id) {
      var d = c[id];
      return { id: id, exists: true, data: function () { return clone(d); } };
    });
    return { docs: docs, size: docs.length, empty: !docs.length, forEach: function (fn) { docs.forEach(fn); } };
  }

  function fire(l) {
    var s = snapshotOf(l.col, l.query);
    setTimeout(function () { try { l.cb(s); } catch (e) { console.error(e); } }, 0);
  }

  function makeQuery(col, q) {
    return {
      orderBy: function (field, dir) { return makeQuery(col, Object.assign({}, q, { orderBy: { field: field, dir: dir || 'asc' } })); },
      limit: function (n) { return makeQuery(col, Object.assign({}, q, { limit: n })); },
      get: function () { return openIdb().then(function () { return snapshotOf(col, q); }); },
      onSnapshot: function (cb, onErr) {
        var l = { col: col, query: q, cb: cb };
        listeners.push(l);
        openIdb().then(function () { fire(l); }).catch(function (e) { if (onErr) onErr(e); });
        return function () { listeners = listeners.filter(function (x) { return x !== l; }); };
      }
    };
  }

  var db = {
    collection: function (col) {
      var q = makeQuery(col, {});
      q.doc = function (id) {
        id = String(id);
        return {
          id: id,
          get: function () {
            return openIdb().then(function () {
              var d = (cache[col] || {})[id];
              return { id: id, exists: d != null, data: function () { return d == null ? undefined : clone(d); } };
            });
          },
          set: function (data) {
            var ops = [{ col: col, id: id, doc: clone(data) }];
            return idbWrite(ops).then(function () { applyLocal(ops); });
          },
          delete: function () {
            var ops = [{ col: col, id: id, doc: null }];
            return idbWrite(ops).then(function () { applyLocal(ops); });
          }
        };
      };
      return q;
    }
  };

  // ------------------------------------------------------------------
  // Respaldo / restauración (JSON)
  // ------------------------------------------------------------------
  function exportAll() {
    return openIdb().then(function () {
      return { app: 'watts-kilos', formato: 1, exportado: new Date().toISOString(), colecciones: clone(cache) };
    });
  }

  function importAll(obj, mode) { // mode: 'merge' | 'replace'
    if (!obj || typeof obj !== 'object' || !obj.colecciones) return Promise.reject(err('invalid_backup', 'El archivo no es un respaldo de Watts & Kilos.'));
    return openIdb().then(function () {
      var ops = [];
      if (mode === 'replace') {
        Object.keys(cache).forEach(function (col) {
          Object.keys(cache[col]).forEach(function (id) { ops.push({ col: col, id: id, doc: null }); });
        });
      }
      var n = 0;
      Object.keys(obj.colecciones).forEach(function (col) {
        var docs = obj.colecciones[col] || {};
        Object.keys(docs).forEach(function (id) { ops.push({ col: col, id: id, doc: docs[id] }); n++; });
      });
      return idbWrite(ops).then(function () { applyLocal(ops); return n; });
    });
  }

  function counts() {
    return openIdb().then(function () {
      var r = {};
      Object.keys(cache).forEach(function (c) { r[c] = Object.keys(cache[c]).length; });
      return r;
    });
  }

  // ------------------------------------------------------------------
  // Descargas / compartir (iOS: hoja de compartir → "Guardar en Archivos")
  // ------------------------------------------------------------------
  function mimeFor(name) {
    if (/\.json$/i.test(name)) return 'application/json';
    if (/\.csv$/i.test(name)) return 'text/csv';
    if (/\.md$/i.test(name)) return 'text/markdown';
    return 'text/plain';
  }
  function saveFile(opts) {
    var name = opts.filename || 'archivo.txt';
    var type = opts.mimeType || mimeFor(name);
    var blob = opts.data instanceof Blob ? opts.data : new Blob([opts.data], { type: type + ';charset=utf-8' });
    var file;
    try { file = new File([blob], name, { type: type }); } catch (e) { file = null; }
    if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
      return navigator.share({ files: [file], title: name }).catch(function (e) {
        if (e && e.name === 'AbortError') throw err('declined');
        throw e;
      });
    }
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1500);
    return Promise.resolve();
  }
  var downloads = { save: saveFile };

  // ------------------------------------------------------------------
  // Claude (API de Anthropic, directo desde el navegador)
  // ------------------------------------------------------------------
  var sdkPromise = null;
  function loadSdk() {
    if (!sdkPromise) sdkPromise = import(SDK_URL).then(function (m) { return m.default || m.Anthropic; });
    return sdkPromise;
  }
  function client() {
    var key = lsGet(LS.key);
    if (!key) return Promise.reject(err('not_granted', 'Falta la API key'));
    return loadSdk().then(function (Anthropic) {
      return new Anthropic({ apiKey: key, dangerouslyAllowBrowser: true, maxRetries: 2 });
    });
  }

  // Fotos del iPhone (HEIC/JPG de varios MB) → JPEG ≤1568 px para la API
  function fileToImageBlock(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        var max = 1568, w = img.naturalWidth, h = img.naturalHeight;
        var s = Math.min(1, max / Math.max(w, h));
        var cv = document.createElement('canvas');
        cv.width = Math.round(w * s); cv.height = Math.round(h * s);
        cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
        URL.revokeObjectURL(url);
        var data = cv.toDataURL('image/jpeg', 0.85).split(',')[1];
        resolve({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: data } });
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(err('image_rejected')); };
      img.src = url;
    });
  }

  function mapError(e, text) {
    if (e && e.code && typeof e.code === 'string' && !e.status) return e;
    var out;
    if (e && (e.name === 'AbortError' || /abort/i.test(e.name || '') || /aborted/i.test(e.message || ''))) out = err('cancelled');
    else if (e && (e.status === 401 || e.status === 403)) out = err('not_granted', 'API key inválida');
    else if (e && e.status === 429) out = err('rate_limited');
    else if (e && e.status === 529) out = err('overloaded');
    else if (e && e.status === 400 && /image/i.test(e.message || '')) out = err('image_rejected');
    else if (e && e.status) out = err('http_' + e.status, e.message);
    else out = err('network', e && e.message);
    if (text) out.text = text;
    return out;
  }

  // sample(prompt, { signal, onText, images, modelTier }) → { text, truncated }
  function sample(prompt, opts) {
    opts = opts || {};
    var complex = opts.modelTier === 'complex';
    var acc = '';
    return client().then(function (c) {
      var imgs = (opts.images || []).slice(0, 5);
      return Promise.all(imgs.map(fileToImageBlock)).then(function (blocks) {
        var content = blocks.concat([{ type: 'text', text: prompt }]);
        var model = lsGet(LS.model) || DEFAULT_MODEL;
        var params = {
          model: model,
          max_tokens: complex ? 16000 : 4000,
          thinking: { type: 'adaptive' },
          output_config: { effort: complex ? 'high' : 'low' },
          messages: [{ role: 'user', content: content }]
        };
        // Respaldo del servidor si el modelo rechaza la solicitud (no disponible en Haiku)
        if (/^claude-(opus|sonnet)-5-5$/.test(model)) {
          params.betas = ['server-side-fallback-2026-07-01'];
          params.fallbacks = 'default';
        }
        var stream = c.beta.messages.stream(params, { signal: opts.signal });
        stream.on('text', function (delta) {
          acc += delta;
          if (opts.onText) { try { opts.onText({ text: acc }); } catch (e) {} }
        });
        return stream.finalMessage();
      });
    }).then(function (msg) {
      if (msg.stop_reason === 'refusal') throw err('refused');
      var text = msg.content.filter(function (b) { return b.type === 'text'; }).map(function (b) { return b.text; }).join('');
      return { text: text, truncated: msg.stop_reason === 'max_tokens' };
    }).catch(function (e) { throw mapError(e, acc); });
  }
  sample.json = function (prompt, opts) {
    return sample(prompt, opts).then(function (r) {
      var a = r.text.indexOf('{'), b = r.text.lastIndexOf('}');
      try { return JSON.parse(r.text.slice(a, b + 1)); } catch (e) { throw err('invalid_json'); }
    });
  };
  sample.limits = function () {
    return Promise.resolve({ images: { mediaTypes: ['image/*'] } });
  };

  // ------------------------------------------------------------------
  // Perfil personal (nombre, nacimiento, altura, contexto médico, textos).
  // Vive en meta/perfil (viaja en el respaldo) con copia en localStorage
  // para leerlo de forma síncrona al arrancar. El código público es genérico.
  // ------------------------------------------------------------------
  var PERFIL_LS = 'wk.perfil';
  var perfilRaw = lsGet(PERFIL_LS);
  try { window.PERFIL = perfilRaw ? JSON.parse(perfilRaw) : {}; } catch (e) { window.PERFIL = {}; }

  function edadDe(nac) {
    if (!nac) return null;
    var b = new Date(nac + 'T12:00:00'), d = new Date();
    var a = d.getFullYear() - b.getFullYear();
    if (d.getMonth() < b.getMonth() || (d.getMonth() === b.getMonth() && d.getDate() < b.getDate())) a--;
    return a;
  }
  function aplicarPerfil() {
    var P = window.PERFIL || {}, t = P.textos || {};
    document.querySelectorAll('[data-perfil]').forEach(function (el) {
      var k = el.getAttribute('data-perfil');
      if (typeof t[k] === 'string' && t[k]) el.innerHTML = t[k];
    });
    var sub = document.getElementById('perfil-subtitulo');
    if (sub) {
      var parts = [];
      if (P.nombre) parts.push(P.nombre);
      var e = edadDe(P.nacimiento); if (e != null) parts.push(e + ' años');
      if (P.altura_cm) parts.push((P.altura_cm / 100).toFixed(2) + ' m');
      parts.push(parts.length ? 'sistema de recomposición corporal' : 'Sistema de recomposición corporal');
      sub.textContent = parts.join(' · ');
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', aplicarPerfil); else aplicarPerfil();

  // Si el perfil guardado en la base difiere de la copia local (p. ej. tras importar
  // un respaldo), se actualiza la copia y se recarga una vez para aplicarlo.
  function syncPerfil() {
    var d = (cache.meta || {}).perfil;
    var now = d ? JSON.stringify(d) : null;
    if (now !== (lsGet(PERFIL_LS) || null)) {
      lsSet(PERFIL_LS, now);
      location.reload();
    }
  }
  listeners.push({ col: 'meta', query: {}, cb: syncPerfil });
  openIdb().then(syncPerfil).catch(function () {});

  // ------------------------------------------------------------------
  // window.claude compatible
  // ------------------------------------------------------------------
  window.claude = {
    use: function (cap) {
      if (cap === 'db') {
        if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(function () {});
        return openIdb().then(function () { return db; });
      }
      if (cap === 'sample') return Promise.resolve(lsGet(LS.key) ? sample : null);
      if (cap === 'downloads') return Promise.resolve(downloads);
      return Promise.resolve(null);
    }
  };

  // API para el panel de Ajustes
  window.WK = {
    exportAll: exportAll,
    importAll: importAll,
    counts: counts,
    saveFile: saveFile,
    getKey: function () { return lsGet(LS.key) || ''; },
    setKey: function (k) { lsSet(LS.key, (k || '').trim()); },
    getModel: function () { return lsGet(LS.model) || DEFAULT_MODEL; },
    setModel: function (m) { lsSet(LS.model, m); },
    getPerfil: function () { return clone(window.PERFIL || {}); },
    setPerfil: function (p) { return db.collection('meta').doc('perfil').set(p); },
    getLastBackup: function () { return lsGet(LS.lastBackup); },
    markBackup: function () { lsSet(LS.lastBackup, new Date().toISOString()); },
    testKey: function () {
      return sample('Responde solo con la palabra: ok', { modelTier: 'default' }).then(function (r) { return r.text; });
    }
  };
})();
