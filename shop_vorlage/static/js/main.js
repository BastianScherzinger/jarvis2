/* ═══════════════════════════════════════════════════
   MAIN.JS – Core UI interactions
   ═══════════════════════════════════════════════════ */

'use strict';

// ── Page Loader ───────────────────────────────────
const loader = document.getElementById('page-loader');
if (loader) {
  window.addEventListener('load', () => {
    setTimeout(() => loader.classList.add('hidden'), 600);
  });
  // Fallback
  setTimeout(() => loader && loader.classList.add('hidden'), 2500);
}

// ── Navbar scroll effect ──────────────────────────
(function initNavbarScroll() {
  const nav = document.querySelector('.sn-nav');
  if (!nav) return;

  const onScroll = () => {
    nav.classList.toggle('scrolled', window.scrollY > 20);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();

// ── Mobile burger ─────────────────────────────────
(function initMobileBurger() {
  const burger = document.getElementById('sn-burger');
  const mobileMenu = document.getElementById('sn-mobile');
  if (!burger || !mobileMenu) return;

  burger.addEventListener('click', () => {
    const isOpen = mobileMenu.classList.toggle('open');
    burger.classList.toggle('open', isOpen);
    burger.setAttribute('aria-expanded', isOpen);
    document.body.style.overflow = isOpen ? 'hidden' : '';
  });

  // Close on outside click
  document.addEventListener('click', (e) => {
    if (!burger.contains(e.target) && !mobileMenu.contains(e.target)) {
      mobileMenu.classList.remove('open');
      burger.classList.remove('open');
      burger.setAttribute('aria-expanded', false);
      document.body.style.overflow = '';
    }
  });

  // Close on link click
  mobileMenu.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
      mobileMenu.classList.remove('open');
      burger.classList.remove('open');
      burger.setAttribute('aria-expanded', false);
      document.body.style.overflow = '';
    });
  });
})();

// ── Toast dismiss ─────────────────────────────────
document.addEventListener('click', (e) => {
  if (e.target.closest('.sn-toast-close')) {
    const toast = e.target.closest('.sn-toast');
    if (toast) {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 400);
    }
  }
});

// Auto-dismiss toasts after 5s
document.querySelectorAll('.sn-toast').forEach(toast => {
  setTimeout(() => {
    if (toast && toast.parentNode) {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 400);
    }
  }, 5000);
});

// ── Scroll-reveal observer ────────────────────────
(function initScrollReveal() {
  const els = document.querySelectorAll('[data-reveal]');
  if (!els.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });

  els.forEach(el => observer.observe(el));
})();

// ── Active nav link highlight ─────────────────────
(function highlightActiveNav() {
  const current = window.location.pathname;
  document.querySelectorAll('.sn-link, .sidebar-link').forEach(link => {
    const href = link.getAttribute('href');
    if (href && href !== '/' && current.startsWith(href)) {
      link.classList.add('active');
    } else if (href === '/' && current === '/') {
      link.classList.add('active');
    }
  });
})();

// ── Sidebar mobile toggle ─────────────────────────
(function initSidebarToggle() {
  const toggle = document.getElementById('sidebar-toggle');
  const sidebar = document.querySelector('.sidebar');
  if (!toggle || !sidebar) return;

  toggle.addEventListener('click', () => {
    sidebar.classList.toggle('open');
  });
})();

// ── Smooth counter animation ──────────────────────
(function initCounters() {
  const counters = document.querySelectorAll('[data-count]');
  if (!counters.length) return;

  const animate = (el) => {
    const target = parseInt(el.dataset.count, 10);
    const duration = 1200;
    const start = performance.now();

    const update = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(eased * target).toLocaleString('de-DE');
      if (progress < 1) requestAnimationFrame(update);
    };
    requestAnimationFrame(update);
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        animate(entry.target);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.5 });

  counters.forEach(el => observer.observe(el));
})();

// ── Dark/Light mode toggle (prepared) ────────────
(function initThemeToggle() {
  const toggle = document.getElementById('theme-toggle');
  if (!toggle) return;

  const stored = localStorage.getItem('theme');
  if (stored === 'light') document.documentElement.classList.add('theme-light');

  toggle.addEventListener('click', () => {
    const isLight = document.documentElement.classList.toggle('theme-light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
  });
})();
