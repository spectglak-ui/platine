const { app, BrowserWindow, Menu, globalShortcut, ipcMain, screen } = require('electron');
const path = require('path');
const fs = require('fs');

let win = null;
let isOnTop = false;
const configPath = path.join(__dirname, 'config.json');

function loadConfig() {
  try { return JSON.parse(fs.readFileSync(configPath, 'utf8')); }
  catch { return { x: null, y: null }; }
}
function saveConfig(cfg) {
  try { fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2)); } catch {}
}

function createWindow() {
  const cfg = loadConfig();
  const { workArea } = screen.getPrimaryDisplay();

  win = new BrowserWindow({
    width: 360,
    height: 110,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: false,       // ★ PAS toujours au-dessus par défaut
    skipTaskbar: true,
    hasShadow: false,
    autoHideMenuBar: true,
    backgroundColor: '#00000000',
    vibrancy: 'acrylic',
    visualEffectState: 'active',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (typeof cfg.x === 'number' && typeof cfg.y === 'number') {
    win.setPosition(cfg.x, cfg.y);
  } else {
    win.setPosition(workArea.x + workArea.width - 400, workArea.y + 60);
  }

  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.loadFile('widget.html');

  win.on('moved', () => {
    const [x, y] = win.getPosition();
    saveConfig({ ...loadConfig(), x, y });
  });

  win.on('closed', () => { win = null; });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    createWindow();

    // ★ Alt+V : bascule entre "niveau bureau" et "au-dessus de tout"
    globalShortcut.register('Alt+V', () => {
      if (!win) return;
      isOnTop = !isOnTop;
      win.setAlwaysOnTop(isOnTop);
      if (isOnTop) win.focus();
    });

    // Ctrl+Alt+M : masquer/afficher complètement
    globalShortcut.register('CommandOrControl+Alt+M', () => {
      if (!win) return;
      if (win.isVisible()) win.hide();
      else { win.show(); win.focus(); }
    });
  });
}

ipcMain.handle('get-config', () => loadConfig());
ipcMain.on('window-close', () => app.quit());

app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => app.quit());