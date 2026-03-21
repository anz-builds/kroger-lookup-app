const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronLoginAPI', {
  extractAndClose: () => ipcRenderer.invoke('kroger:extract-and-close'),
});
