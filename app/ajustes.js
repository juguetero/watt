/* Panel de Ajustes, aviso de respaldo y service worker. Depende de runtime.js (window.WK). */
(function () {
  'use strict';
  var WK = window.WK;
  if (!WK) return;
  function $(id) { return document.getElementById(id); }
  function msg(el, text, color) { el.textContent = text || ''; el.style.color = color || ''; }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function today() { var d = new Date(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function daysSince(iso) { return iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 86400000) : null; }

  var LABELS = { logs: 'Sesiones', medidas: 'Mediciones', comidas: 'Días comida', biblioteca: 'Biblioteca', garmin: 'Días Garmin' };

  function renderCounts() {
    WK.counts().then(function (c) {
      $('aj-counts').innerHTML = Object.keys(LABELS).map(function (k) {
        return '<div><b>' + (c[k] || 0) + '</b><span>' + LABELS[k] + '</span></div>';
      }).join('');
    });
    var last = WK.getLastBackup(), d = daysSince(last);
    $('aj-last').textContent = last ? ('Último respaldo exportado: hace ' + (d === 0 ? 'menos de un día' : d + (d === 1 ? ' día' : ' días')) + '.') : 'Aún no exportas ningún respaldo desde este iPhone.';
    var warn = $('mas-backup-warn');
    if (d == null || d >= 7) {
      warn.innerHTML = '<strong>Respaldo pendiente.</strong> ' + (d == null ? 'Todavía no exportas un respaldo.' : 'Tu último respaldo es de hace ' + d + ' días.') + ' Ve a Ajustes → Exportar respaldo.';
      warn.classList.add('show');
    } else warn.classList.remove('show');
  }

  // ---- Respaldo ----
  $('aj-export').addEventListener('click', function () {
    var m = $('aj-backup-msg');
    WK.exportAll().then(function (data) {
      return WK.saveFile({ filename: 'watt-respaldo-' + today() + '.json', data: JSON.stringify(data, null, 1) });
    }).then(function () {
      WK.markBackup(); renderCounts(); msg(m, 'Respaldo listo ✓', 'var(--good)');
    }).catch(function (e) {
      msg(m, e && e.code === 'declined' ? 'Exportación cancelada.' : 'No se pudo exportar (' + (e && (e.code || e.message) || 'error') + ').', e && e.code === 'declined' ? '' : 'var(--critical)');
    });
  });
  $('aj-import-btn').addEventListener('click', function () { $('aj-import').click(); });
  $('aj-import').addEventListener('change', function (ev) {
    var f = ev.target.files && ev.target.files[0], m = $('aj-backup-msg');
    ev.target.value = '';
    if (!f) return;
    var mode = $('aj-mode').value;
    if (mode === 'replace' && !confirm('Esto borra todos los datos actuales de este iPhone y los reemplaza por el archivo. ¿Continuar?')) return;
    f.text().then(function (t) {
      var obj;
      try { obj = JSON.parse(t); } catch (e) { throw new Error('El archivo no es JSON válido.'); }
      return WK.importAll(obj, mode);
    }).then(function (n) {
      msg(m, n + ' registros importados ✓', 'var(--good)'); renderCounts();
    }).catch(function (e) { msg(m, e.message || 'No se pudo importar.', 'var(--critical)'); });
  });

  // ---- Perfil ----
  (function () {
    var P = WK.getPerfil();
    $('pf-nombre').value = P.nombre || '';
    $('pf-nac').value = P.nacimiento || '';
    $('pf-alt').value = P.altura_cm || '';
    $('pf-ctx').value = P.contexto_medico || '';
    $('pf-esp').value = P.especialista || '';
    $('pf-save').addEventListener('click', function () {
      var alt = parseInt($('pf-alt').value, 10);
      var next = Object.assign(WK.getPerfil(), {
        nombre: $('pf-nombre').value.trim(),
        nacimiento: $('pf-nac').value,
        altura_cm: alt >= 120 && alt <= 230 ? alt : null,
        contexto_medico: $('pf-ctx').value.trim(),
        especialista: $('pf-esp').value.trim()
      });
      msg($('pf-msg'), 'Guardando…');
      WK.setPerfil(next).catch(function () { msg($('pf-msg'), 'No se pudo guardar.', 'var(--critical)'); });
      // al guardar, runtime.js detecta el cambio y recarga la app
    });
  })();

  // ---- Claude ----
  var key = $('aj-key'), model = $('aj-model'), km = $('aj-key-msg');
  function keyState() {
    var k = WK.getKey();
    msg(km, k ? 'Key guardada (…' + k.slice(-4) + '). Claude está activo.' : 'Sin API key: la estimación de comidas y el informe están desactivados.', k ? 'var(--good)' : '');
  }
  key.value = WK.getKey();
  model.value = WK.getModel();
  keyState();
  model.addEventListener('change', function () { WK.setModel(model.value); msg(km, 'Modelo guardado ✓', 'var(--good)'); });
  $('aj-key-save').addEventListener('click', function () {
    var v = key.value.trim();
    if (v && !/^sk-ant-/.test(v)) { msg(km, 'Eso no parece una API key de Anthropic (empieza con sk-ant-).', 'var(--critical)'); return; }
    var changed = v !== WK.getKey();
    WK.setKey(v); WK.setModel(model.value);
    if (changed) { msg(km, 'Guardado. Recargando para activar Claude…', 'var(--good)'); setTimeout(function () { location.reload(); }, 700); }
    else keyState();
  });
  $('aj-key-clear').addEventListener('click', function () {
    if (!WK.getKey()) return;
    if (!confirm('¿Borrar la API key de este iPhone?')) return;
    WK.setKey(''); key.value = ''; location.reload();
  });
  $('aj-key-test').addEventListener('click', function () {
    if (!WK.getKey()) { msg(km, 'Primero guarda una API key.', 'var(--critical)'); return; }
    msg(km, 'Probando…');
    WK.testKey().then(function () { msg(km, 'Conexión OK con ' + WK.getModel() + ' ✓', 'var(--good)'); })
      .catch(function (e) {
        var c = e && e.code;
        msg(km, c === 'not_granted' ? 'La API key no es válida.' : c === 'network' ? 'Sin conexión a internet.' : 'Error: ' + (c || 'desconocido') + (e && e.message ? ' — ' + e.message : ''), 'var(--critical)');
      });
  });

  // ---- Instalación ----
  var standalone = window.navigator.standalone === true || (window.matchMedia && matchMedia('(display-mode: standalone)').matches);
  function installInfo() {
    var parts = [standalone ? 'Abierta como app ✓' : 'Abierta en el navegador (instálala con los pasos de arriba).'];
    var p = navigator.storage && navigator.storage.persisted ? navigator.storage.persisted() : Promise.resolve(null);
    p.then(function (ok) {
      if (ok === true) parts.push('Almacenamiento persistente ✓');
      else if (ok === false && !standalone) parts.push('Ojo: en Safari sin instalar, iOS puede borrar datos de sitios que no visitas en 7 días.');
      $('aj-install').textContent = parts.join(' · ');
    });
  }
  installInfo();
  if (standalone) document.documentElement.classList.add('standalone');

  document.addEventListener('wk:tab', function (e) { if (e.detail === 'ajustes' || e.detail === 'mas') renderCounts(); });
  renderCounts();

  // ---- Service worker (modo sin conexión) ----
  if ('serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('sw.js').then(function (reg) {
      $('aj-version').textContent = 'Watts & Kilos · app personal no oficial · disponible sin conexión';
      reg.addEventListener('updatefound', function () {
        var w = reg.installing;
        if (w) w.addEventListener('statechange', function () {
          if (w.state === 'installed' && navigator.serviceWorker.controller) {
            $('aj-version').textContent = 'Hay una versión nueva: cierra y vuelve a abrir la app.';
          }
        });
      });
    }).catch(function () {});
  }
})();
