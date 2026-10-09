const { app, BrowserWindow, Menu, globalShortcut, ipcMain, screen, desktopCapturer } = require('electron');
const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');

const wins = { player: null, playlists: null };
let isOnTop = false;
const configPath = path.join(__dirname, 'config.json');

function loadConfig() {
  try { return JSON.parse(fs.readFileSync(configPath, 'utf8')); }
  catch { return {}; }
}
function saveConfig(cfg) {
  try { fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2)); } catch {}
}

// Envoie une fenêtre tout en bas (niveau bureau)
async function sendToBottom(win) {
  if (!win) return;
  win.setAlwaysOnTop(false);
  try {
    const sources = await desktopCapturer.getSources({
      types: ['window'], thumbnailSize: { width: 1, height: 1 }
    });
    const desktop = sources.find(s =>
      /program manager|folderview|desktop|bureau/i.test(s.name || ''));
    if (desktop) { win.moveAbove(desktop.id); return; }
  } catch (e) {}
  try {
    const h = win.getNativeWindowHandle();
    const hwnd = h.readBigUInt64LE(0).toString();
    const cs = 'using System;using System.Runtime.InteropServices;' +
      'public class ZOrder{[DllImport("user32.dll")]' +
      'public static extern bool SetWindowPos(IntPtr hWnd,IntPtr hWndInsertAfter,' +
      'int X,int Y,int cx,int cy,uint uFlags);}';
    const cmd = `Add-Type -TypeDefinition '${cs}' ; ` +
      `[ZOrder]::SetWindowPos([IntPtr]::new(${hwnd}),[IntPtr]::new(1),0,0,0,0,0x0013) | Out-Null`;
    execFile('powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd],
      { windowsHide: true }, () => {});
  } catch (e) {}
}

function createWindow(mode) {
  const cfg = loadConfig();
  const { workArea } = screen.getPrimaryDisplay();
  const isPlayer = (mode === 'player');

  const win = new BrowserWindow({
    width: isPlayer ? 360 : 340,
    height: isPlayer ? 110 : 440,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: false,
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

  const x = isPlayer ? (cfg.playerX ?? workArea.x + workArea.width - 400)
                     : (cfg.playlistX ?? workArea.x + workArea.width - 400);
  const y = isPlayer ? (cfg.playerY ?? workArea.y + 60)
                     : (cfg.playlistY ?? workArea.y + 190);
  win.setPosition(x, y);

  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.loadFile('widget.html', { query: { mode } });
  win.webContents.once('did-finish-load', () => sendToBottom(win));

  win.on('moved', () => {
    const [mx, my] = win.getPosition();
    const c = loadConfig();
    if (isPlayer) { c.playerX = mx; c.playerY = my; }
    else { c.playlistX = mx; c.playlistY = my; }
    saveConfig(c);
  });

  win.on('closed', () => { wins[mode] = null; });
  wins[mode] = win;
  return win;
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    createWindow('player');
    createWindow('playlists');

    // Alt+V : les DEUX widgets passent au-dessus / retour bureau
    globalShortcut.register('Alt+V', () => {
      isOnTop = !isOnTop;
      for (const w of Object.values(wins)) {
        if (!w) continue;
        if (isOnTop) { w.setAlwaysOnTop(true, 'screen-saver'); w.show(); w.focus(); }
        else sendToBottom(w);
      }
    });

    // Ctrl+Alt+M : masquer / afficher les deux
    globalShortcut.register('CommandOrControl+Alt+M', () => {
      const anyVisible = Object.values(wins).some(w => w && w.isVisible());
      for (const w of Object.values(wins)) {
        if (!w) continue;
        if (anyVisible) w.hide();
        else { w.show(); if (!isOnTop) sendToBottom(w); }
      }
    });
  });
}

ipcMain.handle('get-config', () => loadConfig());
ipcMain.on('set-locked', (event, locked) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const c = loadConfig();
  if (win === wins.player) c.lockedPlayer = locked;
  else c.lockedPlaylists = locked;
  saveConfig(c);
});
ipcMain.on('window-close', () => app.quit());

app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => app.quit());