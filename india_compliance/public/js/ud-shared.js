/* Shared dashboard behaviour: mobile menu + admin-only links. */
(function () {
  var btn = document.getElementById('menu-btn');
  if (btn) {
    btn.addEventListener('click', function () {
      var open = document.body.classList.toggle('menu-open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && document.body.classList.contains('menu-open')) {
        document.body.classList.remove('menu-open');
        btn.setAttribute('aria-expanded', 'false');
        btn.focus();
      }
    });
  }
  // Called by each page's user-info callback only when the user is an admin.
  window.udShowAdminLinks = function () {
    document.querySelectorAll('[data-admin-only]').forEach(function (el) { el.hidden = false; });
  };
})();

/* Session wiring shared by all six dashboards.
   udInit('Retail') fills the sidebar, sends signed-out visitors to login,
   and sends non-admins whose business type differs to their own dashboard. */
(function () {
  var API = '/api/method/india_compliance.gst_india.api.portal_management.';
  function csrf() {
    return (window.frappe && frappe.csrf_token) ||
      ((document.cookie.match(/csrf_token=([^;]+)/) || [])[1]) || '';
  }
  window.doLogout = function () {
    var btn = document.querySelector('.logout-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Signing out…'; }
    fetch(API + 'portal_logout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': csrf(), 'X-Requested-With': 'XMLHttpRequest'},
      body: '{}'
    }).catch(function () {}).then(function () { window.location.href = '/gst-login'; });
  };
  window.udInit = function (industry) {
    var set = function (id, text) { var el = document.getElementById(id); if (el && text) el.textContent = text; };
    fetch(API + 'get_current_user_info').then(function (r) { return r.json(); }).then(function (res) {
      var info = res.message || {};
      if (info.redirect_to_login) { window.location.href = '/gst-login'; return; }
      set('ud-email', info.email);
      if (info.company_name) { set('ud-title', info.company_name); set('ud-company', info.company_name); }
      if (info.is_admin) {
        var badge = document.getElementById('ud-role-badge');
        if (badge) { badge.textContent = 'ADMIN'; badge.className = 'user-role-badge role-admin'; }
        window.udShowAdminLinks();
      } else if (info.industry_type && info.industry_type !== industry) {
        window.location.href = info.dashboard_url || '/gst-login';
      }
    }).catch(function () {
      set('ud-email', 'Could not load your account — refresh to retry');
    });
  };
})();
