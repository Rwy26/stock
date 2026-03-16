function getCurrentRoute() {
  const pageAttr = document.querySelector('.app-shell')?.getAttribute('data-page');
  if (pageAttr) return pageAttr;

  const path = (location.pathname || '').replace(/\\/g, '/');
  const file = path.split('/').pop() || '';

  if (file === '' || file === 'index.html') return 'dashboard';
  return file.replace(/\.html$/i, '');
}

function setActiveMenu() {
  const current = getCurrentRoute();
  const menuItems = document.querySelectorAll('.menu[data-route]');
  menuItems.forEach((item) => item.classList.remove('active'));
  const active = document.querySelector(`.menu[data-route="${current}"]`);
  if (active) active.classList.add('active');
}

function wireExclusiveButtons(selector) {
  const buttons = document.querySelectorAll(selector);
  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      buttons.forEach((candidate) => candidate.classList.remove('active'));
      button.classList.add('active');
    });
  });
}

function wireTabs() {
  const tabs = document.querySelectorAll('[data-tabs]');
  tabs.forEach((tabsRoot) => {
    const tabButtons = tabsRoot.querySelectorAll('[data-tab]');
    const panelsRoot = document.querySelector(`[data-tab-panels="${tabsRoot.getAttribute('data-tabs')}"]`);
    if (!panelsRoot) return;

    const panels = panelsRoot.querySelectorAll('[data-tab-panel]');

    function activate(name) {
      tabButtons.forEach((b) => b.classList.toggle('active', b.getAttribute('data-tab') === name));
      panels.forEach((p) => p.classList.toggle('active', p.getAttribute('data-tab-panel') === name));
    }

    tabButtons.forEach((button) => {
      button.addEventListener('click', () => activate(button.getAttribute('data-tab')));
    });

    const first = tabButtons[0]?.getAttribute('data-tab');
    if (first) activate(first);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setActiveMenu();
  wireExclusiveButtons('.mode');
  wireTabs();
});
