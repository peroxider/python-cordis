/* ============================================================
   python-cordis promo site — main.js
   - Adds a "copy" button to every <pre class="code"> block
   - Marks the current page's nav link as .active
   - Smooth-scroll for in-page anchors
   ============================================================ */

(function () {
  'use strict';

  // ---------- 1. copy buttons on <pre class="code"> ----------
  function attachCopyButtons() {
    var blocks = document.querySelectorAll('pre.code');
    blocks.forEach(function (pre) {
      if (pre.querySelector('.copy-btn')) return; // idempotent

      var btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.type = 'button';
      btn.setAttribute('aria-label', 'Copy code');
      btn.textContent = 'copy';

      btn.addEventListener('click', function () {
        var text = pre.innerText;
        var done = function () {
          btn.textContent = 'copied';
          btn.classList.add('ok');
          setTimeout(function () {
            btn.textContent = 'copy';
            btn.classList.remove('ok');
          }, 1400);
        };
        var fail = function () {
          btn.textContent = 'err';
          setTimeout(function () { btn.textContent = 'copy'; }, 1400);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {
            legacyCopy(text) ? done() : fail();
          });
        } else {
          legacyCopy(text) ? done() : fail();
        }
      });

      pre.appendChild(btn);
    });
  }

  function legacyCopy(text) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'absolute';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (_) { return false; }
  }

  // ---------- 2. active nav link ----------
  function markActiveNav() {
    var path = (location.pathname || '').split('/').pop() || 'index.html';
    if (path === '') path = 'index.html';
    var links = document.querySelectorAll('.nav-links a');
    links.forEach(function (a) {
      var href = a.getAttribute('href') || '';
      if (href === path) a.classList.add('active');
    });
  }

  // ---------- 3. smooth scroll for in-page anchors ----------
  function smoothAnchors() {
    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var id = a.getAttribute('href').slice(1);
        if (!id) return;
        var target = document.getElementById(id);
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        history.replaceState(null, '', '#' + id);
      });
    });
  }

  // ---------- boot ----------
  function init() {
    attachCopyButtons();
    markActiveNav();
    smoothAnchors();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();