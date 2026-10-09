const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('bridge', {
  close: () => ipcRenderer.send('window-close'),
  getConfig: () => ipcRenderer.invoke('get-config'),
  setLocked: (locked) => ipcRenderer.send('set-locked', locked),
  platform: process.platform
});