  // ---------- Tabs (barra inferior iOS) ----------
  var SECONDARY_TABS = { plan: 1, nutricion: 1, analisis: 1, ajustes: 1, mas: 1 };
  function showTab(name){
    var panel = document.getElementById('panel-' + name);
    if(!panel) return;
    document.querySelectorAll('section.panel').forEach(function(p){ p.classList.remove('active'); });
    panel.classList.add('active');
    document.querySelectorAll('nav.tabbar button').forEach(function(b){
      var on = b.dataset.tab === name || (b.dataset.tab === 'mas' && SECONDARY_TABS[name]);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    window.scrollTo(0, 0);
    try { sessionStorage.setItem('wk.tab', name); } catch(e){}
    onTabShown(name);
    document.dispatchEvent(new CustomEvent('wk:tab', { detail: name }));
  }
  document.addEventListener('click', function(e){
    var t = e.target.closest && e.target.closest('[data-tab]');
    if(!t) return;
    e.preventDefault();
    showTab(t.dataset.tab);
  });
  window.wkShowTab = showTab;
  (function(){ var t = null; try { t = sessionStorage.getItem('wk.tab'); } catch(e){} if(t && t !== 'hoy') setTimeout(function(){ showTab(t); }, 0); })();
