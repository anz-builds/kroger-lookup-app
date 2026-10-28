const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Open the Kroger login window
  login: () => ipcRenderer.invoke('kroger:login'),

  // Refresh cookies from persistent session (no login window)
  refreshCookies: () => ipcRenderer.invoke('kroger:refresh-cookies'),

  // Get cookie count from Electron's session store
  getCookieCount: () => ipcRenderer.invoke('kroger:get-cookie-count'),

  // Run an atlas request inside the hidden kroger.com window (in-browser deals)
  atlasFetch: (path, headers) => ipcRenderer.invoke('kroger:atlas-fetch', { path, headers }),

  // Clear saved Kroger session
  clearSession: () => ipcRenderer.invoke('kroger:clear-session'),

  // Listen for cookie updates from main process
  onCookiesUpdated: (callback) => {
    ipcRenderer.on('cookies-updated', (event, data) => callback(data));
  },

  // Check if we're running in Electron
  isElectron: true,
});
