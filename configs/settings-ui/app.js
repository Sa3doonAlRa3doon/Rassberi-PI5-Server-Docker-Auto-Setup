'use strict';

const $ = id => document.getElementById(id);
let state = null;
let token = sessionStorage.getItem('pi-settings-key') || '';
let reviewed = null;

function element(tag, text, cls) {
  const value = document.createElement(tag);
  if (text !== undefined) value.textContent = text;
  if (cls) value.className = cls;
  return value;
}

function notice(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
  $('message').style.display = 'block';
  setTimeout(() => { $('message').style.display = 'none'; }, 7000);
}

async function api(path, data) {
  const response = await fetch('/api/' + path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: { Authorization: 'Bearer ' + token, ...(data === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: data === undefined ? undefined : JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Request failed');
  return result;
}

function switchPanel(name) {
  document.querySelectorAll('.tab').forEach(tab => { tab.hidden = tab.id !== name; });
  document.querySelectorAll('[data-tab]').forEach(tab => tab.classList.toggle('active', tab.dataset.tab === name));
  const titles = {
    overview: 'A home for everything.',
    storage: '1. Choose your storage.',
    apps: '2. Choose your applications.',
    backup: 'Keep a copy. Keep control.',
    access: 'Connected, wherever you are.'
  };
  $('title').textContent = titles[name];
}

document.querySelectorAll('[data-tab]').forEach(tab => tab.addEventListener('click', () => switchPanel(tab.dataset.tab)));
document.querySelectorAll('[data-go]').forEach(tab => tab.addEventListener('click', () => switchPanel(tab.dataset.go)));

const gib = value => (Number(value || 0) / 1024 ** 3).toFixed(1) + ' GiB';

function placements() {
  return Object.fromEntries([...document.querySelectorAll('[data-placement]')].map(input => [input.dataset.placement, input.value.trim()]));
}

function selectionDirty() {
  if (!state) return false;
  const installed = [...document.querySelectorAll('[data-install-app]:checked')].map(input => input.dataset.installApp).sort();
  const startup = [...document.querySelectorAll('[data-app]:checked')].map(input => input.dataset.app).sort();
  return JSON.stringify(installed) !== JSON.stringify([...state.installed].sort()) ||
    JSON.stringify(startup) !== JSON.stringify([...state.enabled].sort());
}

function invalidate() {
  reviewed = null;
  $('apply').disabled = true;
}

function roleDisks(role) {
  const eligible = state.disks.filter(disk => disk.eligible);
  if (role === 'system_uuid') return eligible.filter(disk => disk.kind === 'SSD');
  if (role === 'media_uuid') return eligible.filter(disk => ['microSD', 'SSD', 'HDD'].includes(disk.kind));
  return eligible.filter(disk => ['HDD', 'SSD'].includes(disk.kind));
}

function renderStorageRoles() {
  const roles = [
    ['system_uuid', 'Primary SSD / NVMe', 'Databases, Docker state, appdata and caches.'],
    ['bulk_uuid', 'Bulk files', 'Nextcloud, Paperless, books, Kiwix and shared files.'],
    ['media_uuid', 'Music and videos', 'microSD is preferred; a reviewed SSD/HDD also works.']
  ];
  $('storage-roles').replaceChildren();
  roles.forEach(([key, label, description]) => {
    const wrapper = element('label', undefined, 'storage-role');
    wrapper.append(element('strong', label), element('small', description));
    const select = element('select');
    select.dataset.storageRole = key;
    select.setAttribute('aria-label', label);
    select.append(element('option', 'Let auto-select choose'));
    select.firstChild.value = '';
    roleDisks(key).forEach(disk => {
      const option = element('option', `${disk.kind} · ${disk.mount} · ${gib(disk.free_bytes)} free`);
      option.value = disk.uuid;
      select.append(option);
    });
    select.value = state.storage_preferences?.[key] || '';
    wrapper.append(select);
    $('storage-roles').append(wrapper);
  });
}

function render() {
  $('login').hidden = true;
  $('content').hidden = false;
  $('summary').replaceChildren();
  [
    [state.disks.filter(disk => disk.eligible).length, 'Mounted storage devices'],
    [state.apps.length, 'Available applications'],
    [state.installed.length, 'Selected to install'],
    [state.enabled.length, 'Selected for startup']
  ].forEach(([count, label]) => {
    const box = element('div', undefined, 'stat');
    box.append(element('span', label), element('strong', String(count)));
    $('summary').append(box);
  });

  $('drives').replaceChildren();
  state.disks.forEach(disk => {
    const box = element('article', undefined, 'drive');
    box.append(element('span', disk.kind || 'UNAVAILABLE', 'kind'), element('h3', disk.mount || 'Unmounted drive'), element('p', disk.model || disk.name), element('p', 'UUID · ' + (disk.uuid || 'not available')));
    if (disk.eligible) {
      box.append(element('div', gib(disk.free_bytes) + ' available', 'capacity'));
      const bar = element('div', undefined, 'bar');
      const fill = element('i');
      fill.style.width = Math.max(0, Math.min(100, 100 * (1 - disk.free_bytes / disk.size))) + '%';
      bar.append(fill);
      box.append(bar, element('p', gib(disk.size) + ' device capacity'));
    } else {
      box.append(element('p', disk.reason));
    }
    $('drives').append(box);
  });
  renderStorageRoles();

  $('placement-card').hidden = !state.installed.length;
  $('auto').disabled = !state.installed.length;
  $('placements').replaceChildren();
  state.placements.forEach(row => {
    const tr = element('tr');
    const name = element('td');
    const drive = element('td');
    const destination = element('td');
    name.append(element('strong', row.id.split('/').slice(-2).join('/')), element('small', row.kind + ' · ' + row.apps.join(', ')));
    const input = element('input');
    input.value = row.current;
    input.dataset.placement = row.id;
    input.setAttribute('aria-label', row.id + ' destination');
    input.oninput = invalidate;
    const select = element('select');
    select.setAttribute('aria-label', row.id + ' device');
    const eligible = state.disks.filter(disk => disk.eligible && (row.kind === 'bulk' || disk.kind === 'SSD'));
    eligible.forEach(disk => {
      const option = element('option', disk.kind + ' · ' + disk.mount);
      option.value = disk.mount;
      select.append(option);
    });
    const best = eligible.filter(disk => disk.mount === '/' || row.current.startsWith(disk.mount + '/')).sort((a, b) => b.mount.length - a.mount.length)[0];
    if (best) select.value = best.mount;
    select.onchange = () => {
      const root = select.value === '/' ? '/srv/pi-data' : select.value + '/PiServer';
      input.value = root + '/' + row.id.replace(/^\/srv\/docker\//, '').replace(/^\/mnt\//, '');
      invalidate();
    };
    drive.append(select);
    destination.append(input);
    tr.append(name, drive, destination);
    $('placements').append(tr);
  });

  $('app-grid').replaceChildren();
  state.apps.forEach(app => {
    const box = element('article', undefined, 'app');
    box.dataset.name = app.name;
    const heading = element('h3', app.name.replaceAll('-', ' '));
    const install = element('input');
    install.type = 'checkbox';
    install.checked = state.installed.includes(app.name);
    install.dataset.installApp = app.name;
    install.setAttribute('aria-label', 'Install ' + app.name);
    const installLabel = element('label', 'Install');
    installLabel.prepend(install);
    const startup = element('input');
    startup.type = 'checkbox';
    startup.checked = state.enabled.includes(app.name);
    startup.dataset.app = app.name;
    startup.setAttribute('aria-label', 'Start ' + app.name + ' at boot');
    startup.disabled = !install.checked;
    install.onchange = () => {
      startup.disabled = !install.checked;
      if (!install.checked) startup.checked = false;
      invalidate();
    };
    startup.onchange = invalidate;
    const startupLabel = element('label', 'Start at boot');
    startupLabel.prepend(startup);
    heading.append(installLabel, startupLabel);
    box.append(heading);
    box.append(element('p', app.description, 'app-description'));
    box.append(element('small', (app.memory_mib || '?') + ' MiB declared RAM budget', 'app-memory'));
    const storage = element('div', undefined, 'app-storage');
    storage.append(element('strong', 'Storage: ' + app.storage_class));
    storage.append(element('small', 'Planning: ' + app.storage_estimate));
    const paths = element('ul');
    (app.storage_paths || []).forEach(row => paths.append(element('li', row.kind + ' · ' + row.path)));
    if (!paths.children.length) paths.append(element('li', 'No persistent path declared'));
    storage.append(paths);
    box.append(storage);
    const buttons = element('div', undefined, 'actions');
    ['Start', 'Stop'].forEach(label => {
      const button = element('button', label, 'secondary');
      button.disabled = !state.deployed || !app.installed || !app.prepared;
      button.onclick = () => job('app-' + label.toLowerCase(), { app: app.name });
      buttons.append(button);
    });
    box.append(buttons);
    if (app.installed && !app.prepared) box.append(element('span', 'Install package before starting', 'badge'));
    if (app.default_enabled === false) box.append(element('span', 'On demand by default', 'badge'));
    $('app-grid').append(box);
  });

  $('backup-drive').replaceChildren(element('option', 'Select a separate backup disk'));
  $('backup-drive').firstChild.value = '';
  state.disks.filter(disk => disk.eligible && disk.mount !== '/').forEach(disk => {
    const option = element('option', (disk.model || disk.kind) + ' · ' + disk.mount + ' · ' + gib(disk.free_bytes) + ' free');
    option.value = disk.uuid;
    $('backup-drive').append(option);
  });
  $('backup-drive').value = state.backup.uuid || '';
  $('backup-folder').value = state.backup.folder || 'pi-server';
  $('backup-bulk').checked = state.backup.include_bulk !== false;
  $('backup-daily').checked = state.backup.daily === true;
  $('install').disabled = !(state.selection_saved && state.layout_saved);
  invalidate();
  if (state.fresh_setup && !state.selection_saved) switchPanel('storage');
  if (state.demo) notice('Read-only preview. Unlock key: preview-only. Changes run only on your Pi.');
}

async function refresh() {
  try {
    state = await api('state');
    render();
    if (state.job.running) poll();
  } catch (error) {
    notice(error.message, true);
  }
}

async function job(action, data = {}) {
  try {
    await api(action, data);
    $('operation').hidden = false;
    $('operation-title').textContent = action.replaceAll('-', ' ');
    $('operation-result').textContent = 'Working… You may leave this tab open.';
    return poll();
  } catch (error) {
    notice(error.message, true);
    return null;
  }
}

let polling = false;
async function poll() {
  if (polling) return;
  polling = true;
  try {
    for (;;) {
      const result = await api('job');
      $('operation').hidden = false;
      $('operation-title').textContent = result.name || 'Operation';
      $('operation-result').textContent = result.running ? 'Working… The server keeps a private operation log.' : result.error || JSON.stringify(result.result, null, 2);
      if (!result.running) {
        notice(result.error || 'Operation completed', Boolean(result.error));
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 2500));
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    polling = false;
  }
}

$('login-form').onsubmit = event => {
  event.preventDefault();
  token = $('key').value.trim();
  sessionStorage.setItem('pi-settings-key', token);
  refresh();
};
$('refresh').onclick = refresh;
$('save-storage-preferences').onclick = async () => {
  const preferences = Object.fromEntries([...document.querySelectorAll('[data-storage-role]')].map(select => [select.dataset.storageRole, select.value]));
  await job('save-storage-preferences', preferences);
  await refresh();
};
$('auto').onclick = async () => {
  if (!state.installed.length) return notice('Save your application selection before suggesting app destinations.', true);
  if (selectionDirty()) return notice('Save application selection before suggesting storage.', true);
  try {
    const result = await api('auto-select', {});
    document.querySelectorAll('[data-placement]').forEach(input => { input.value = result.placements[input.dataset.placement]; });
    invalidate();
    notice('Fresh destinations suggested. Review before applying.');
  } catch (error) {
    notice(error.message, true);
  }
};
$('review').onclick = async () => {
  if (!state.installed.length) return notice('Choose at least one application first.', true);
  if (selectionDirty()) return notice('Save application selection before reviewing storage.', true);
  try {
    const proposed = placements();
    const result = await api('layout-plan', { placements: proposed });
    reviewed = JSON.stringify(proposed);
    $('plan').hidden = false;
    $('plan').textContent = JSON.stringify({ changes: result.changes, requires_copy: result.requires_copy, note: result.note }, null, 2);
    $('apply').disabled = false;
  } catch (error) {
    invalidate();
    notice(error.message, true);
  }
};
$('apply').onclick = () => {
  const proposed = placements();
  if (JSON.stringify(proposed) !== reviewed) return notice('Review this layout first.', true);
  invalidate();
  job('layout-apply', { placements: proposed, migrate: $('migrate').checked }).then(refresh);
};
$('save-apps').onclick = async () => {
  const installed = [...document.querySelectorAll('[data-install-app]:checked')].map(input => input.dataset.installApp);
  const enabled = [...document.querySelectorAll('[data-app]:checked')].map(input => input.dataset.app);
  await job('save-apps', { installed, enabled });
  await refresh();
  switchPanel('storage');
  notice('Applications saved. Review their destinations before installing.');
};
$('search').oninput = () => document.querySelectorAll('.app').forEach(app => { app.hidden = !app.dataset.name.includes($('search').value.toLowerCase()); });
$('save-backup').onclick = () => job('save-backup', { uuid: $('backup-drive').value, folder: $('backup-folder').value, include_bulk: $('backup-bulk').checked, daily: $('backup-daily').checked });
['backup-plan', 'backup-create'].forEach(id => { $(id).onclick = () => job(id); });
$('backup-verify').onclick = () => job('backup-verify', { backup: $('snapshot').value });
$('install').onclick = () => {
  if (!state.selection_saved || !state.layout_saved) return notice('Save applications and apply the reviewed storage layout before installing. No Docker images have been pulled.', true);
  job('install');
};
$('tailscale').onclick = () => job('tailscale-configure');
$('enable-panel').onclick = () => job('enable-panel');
$('finish').onclick = async () => {
  try {
    await api('finish', {});
    notice('Temporary setup server closed.');
  } catch (error) {
    notice(error.message, true);
  }
};
if (token) refresh();
