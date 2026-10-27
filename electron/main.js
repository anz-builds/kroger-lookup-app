const { app, BrowserWindow, ipcMain, session, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

// ── Configuration ──
const FASTAPI_PORT = 18234; // Unusual port to avoid conflicts
const KROGER_LOGIN_URL = 'https://www.kroger.com/signin?redirectUrl=/';
const KROGER_DOMAIN = '.kroger.com';

let mainWindow = null;
let loginWindow = null;
let backendProcess = null;

// ── Determine paths ──
function getBackendPath() {
  // In production (packaged), the backend exe is in resources/
  if (app.isPackaged) {
    const exeName = process.platform === 'win32' ? 'kroger-backend.exe' : 'kroger-backend';
    return path.join(process.resourcesPath, 'backend', exeName);
  }
  // In development, run Python directly
  return null; // Will use python instead
}

// ── Start FastAPI backend ──
function startBackend() {
  return new Promise((resolve, reject) => {
    const backendExe = getBackendPath();

    if (backendExe) {
      // Production: run the bundled executable
      console.log(`Starting backend: ${backendExe}`);
      backendProcess = spawn(backendExe, [], {
        env: { ...process.env, PORT: String(FASTAPI_PORT), PYTHONIOENCODING: 'utf-8' },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } else {
      // Development: run with venv Python (fall back to system Python)
      const backendDir = path.join(__dirname, '..', 'kroger-lookup');
      const venvPython = process.platform === 'win32'
        ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
        : path.join(backendDir, '.venv', 'bin', 'python');
      const fs = require('fs');
      const pythonPath = fs.existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3');
      const mainPy = path.join(backendDir, 'main.py');
      console.log(`Starting backend (dev): ${pythonPath} -m uvicorn main:app --port ${FASTAPI_PORT}`);
      backendProcess = spawn(pythonPath, [
        '-m', 'uvicorn', 'main:app',
        '--host', '127.0.0.1',
        '--port', String(FASTAPI_PORT),
      ], {
        cwd: backendDir,
        env: { ...process.env, PORT: String(FASTAPI_PORT), PYTHONIOENCODING: 'utf-8' },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    }

    backendProcess.stdout.on('data', (data) => {
      const msg = data.toString().trim();
      if (msg) console.log(`[backend] ${msg}`);
    });
    backendProcess.stderr.on('data', (data) => {
      const msg = data.toString().trim();
      if (msg) console.log(`[backend] ${msg}`);
    });
    backendProcess.on('error', (err) => {
      console.error('Backend failed to start:', err);
      reject(err);
    });
    backendProcess.on('exit', (code) => {
      console.log(`Backend exited with code ${code}`);
      backendProcess = null;
    });

    // Poll until the backend is ready
    let attempts = 0;
    const maxAttempts = 40; // 40 * 500ms = 20 seconds
    const check = () => {
      attempts++;
      const req = http.get(`http://127.0.0.1:${FASTAPI_PORT}/api/atlas-cookies/status`, (res) => {
        if (res.statusCode === 200) {
          console.log(`Backend ready after ${attempts * 500}ms`);
          resolve();
        } else if (attempts < maxAttempts) {
          setTimeout(check, 500);
        } else {
          reject(new Error('Backend did not become ready'));
        }
      });
      req.on('error', () => {
        if (attempts < maxAttempts) {
          setTimeout(check, 500);
        } else {
          reject(new Error('Backend did not start'));
        }
      });
      req.end();
    };
    setTimeout(check, 800); // Initial delay for Python to import
  });
}

// ── Stop backend ──
function stopBackend() {
  if (backendProcess) {
    console.log('Stopping backend...');
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(backendProcess.pid), '/f', '/t']);
    } else {
      backendProcess.kill('SIGTERM');
    }
    backendProcess = null;
  }
}

// ── Create main window ──
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    title: 'Kroger Price Lookup',
    icon: path.join(__dirname, 'build', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // The app UI is the only page this window (and its preload API) may show.
  // Links (target=_blank, window.open, or a plain navigation) go to the system browser instead.
  const appOrigin = `http://127.0.0.1:${FASTAPI_PORT}`;
  const openExternal = (url) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
  };
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(appOrigin + '/')) {
      event.preventDefault();
      openExternal(url);
    }
  });

  mainWindow.loadURL(`${appOrigin}/`);
  mainWindow.on('closed', () => { mainWindow = null; });

  // Remove default menu bar (optional — keeps it clean)
  mainWindow.setMenuBarVisibility(false);
}

// ── Login window ──
function openLoginWindow() {
  if (loginWindow) {
    loginWindow.focus();
    return;
  }

  loginWindow = new BrowserWindow({
    width: 1100,
    height: 800,
    title: 'Sign in to Kroger — Select your store for Pickup, then click Done',
    parent: mainWindow,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload-login.js'),
      partition: 'persist:kroger',
    },
  });

  loginWindow.setMenuBarVisibility(false);
  loginWindow.loadURL(KROGER_LOGIN_URL);

  let loggedIn = false;

  // Inject floating "Done" banner after each page load
  const injectBanner = () => {
    const bannerJS = `
    (function() {
      if (document.getElementById('electron-banner')) return;
      var bar = document.createElement('div');
      bar.id = 'electron-banner';
      bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:#0053A0;color:#fff;padding:8px 16px;display:flex;align-items:center;justify-content:space-between;font-family:sans-serif;font-size:14px;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
      
      var msg = document.createElement('span');
      msg.textContent = ${loggedIn
        ? "'✓ Logged in — select your store for Pickup (not Delivery), then click Done →'"
        : "'Sign in to Kroger, then select a store for Pickup'"
      };
      bar.appendChild(msg);

      ${loggedIn ? `
      var btn = document.createElement('button');
      btn.textContent = '✓ Done — Extract Session';
      btn.style.cssText = 'background:#fff;color:#0053A0;border:none;border-radius:6px;padding:8px 20px;font-weight:700;font-size:14px;cursor:pointer;';
      btn.onclick = function() {
        btn.textContent = 'Extracting...';
        btn.disabled = true;
        window.electronLoginAPI.extractAndClose();
      };
      bar.appendChild(btn);
      ` : ''}

      document.body.style.paddingTop = '44px';
      document.body.insertBefore(bar, document.body.firstChild);
    })()
    `;
    loginWindow.webContents.executeJavaScript(bannerJS).catch(() => {});
  };

  // Watch for successful login
  loginWindow.webContents.on('did-navigate', (event, url) => {
    console.log(`Login window navigated: ${url}`);
    if (url.includes('kroger.com') && !url.includes('signin') && !url.includes('account/create')) {
      loggedIn = true;
      loginWindow.setTitle('Kroger — Select your store for Pickup, then click Done');
    }
    // Re-inject banner on every navigation
    setTimeout(injectBanner, 500);
  });

  loginWindow.webContents.on('did-finish-load', () => {
    setTimeout(injectBanner, 300);
  });

  loginWindow.on('closed', () => { loginWindow = null; });
}

// ── Extract cookies from Electron session and send to FastAPI ──
async function extractAndSendCookies() {
  try {
    // Get cookies from the kroger partition
    const krogerSession = session.fromPartition('persist:kroger');
    const allCookies = await krogerSession.cookies.get({ domain: KROGER_DOMAIN });

    if (!allCookies.length) {
      console.log('No kroger.com cookies found');
      return { ok: false, message: 'No cookies found' };
    }

    // Build cookie string
    const cookieStr = allCookies
      .map(c => `${c.name}=${c.value}`)
      .join('; ');

    console.log(`Extracted ${allCookies.length} cookies from Electron session`);

    // Capture real LAF by intercepting request headers via Electron's webRequest API
    let lafData = '';
    if (loginWindow && !loginWindow.isDestroyed()) {
      try {
        console.log('Attempting LAF capture via webRequest interception...');

        // Set up a header interceptor on the kroger session
        lafData = await new Promise((resolve) => {
          const timeout = setTimeout(() => {
            console.log('LAF capture timed out after 8s');
            krogerSession.webRequest.onBeforeSendHeaders(null); // remove listener
            resolve('');
          }, 8000);

          krogerSession.webRequest.onBeforeSendHeaders(
            { urls: ['*://*.kroger.com/atlas/*'] },
            (details, callback) => {
              // Check for x-laf-object in the outgoing request headers
              const headers = details.requestHeaders;
              const lafHeader = headers['x-laf-object'] || headers['X-Laf-Object'] || '';
              
              console.log(`  webRequest intercepted: ${details.url.substring(0, 80)}`);
              console.log(`  Headers present: ${Object.keys(headers).filter(k => k.toLowerCase().startsWith('x-')).join(', ')}`);

              if (lafHeader && lafHeader.includes('modality')) {
                clearTimeout(timeout);
                console.log(`Captured real LAF via webRequest (${lafHeader.length} chars)`);
                krogerSession.webRequest.onBeforeSendHeaders(null); // remove listener
                resolve(lafHeader);
              }

              // Let the request continue normally
              callback({ requestHeaders: headers });
            }
          );

          // Trigger a small atlas request from the Kroger page
          loginWindow.webContents.executeJavaScript(`
            (function() {
              console.log('[Electron] Triggering atlas request for LAF capture...');
              fetch('/atlas/v1/product/v2/products?filter.verified=true&filter.gtin13s=0001111042545&projections=items.full', {
                credentials: 'include'
              }).then(function(r) {
                console.log('[Electron] Atlas fetch status:', r.status);
              }).catch(function(e) {
                console.log('[Electron] Atlas fetch error:', e.message);
              });
            })()
          `).catch((err) => {
            console.log('Could not trigger atlas fetch:', err.message);
          });
        });

      } catch (e) {
        console.log('webRequest LAF capture failed:', e.message);
      }

      // Method 2: Fall back to localStorage/sessionStorage
      if (!lafData) {
        console.log('Trying localStorage/sessionStorage fallback...');
        try {
          lafData = await loginWindow.webContents.executeJavaScript(`
            (function() {
              try {
                var keys = Object.keys(localStorage);
                for (var i = 0; i < keys.length; i++) {
                  var v = localStorage.getItem(keys[i]);
                  if (v && v.indexOf('handoffLocation') !== -1 && v.indexOf('modality') !== -1) {
                    return v;
                  }
                }
              } catch(e) {}
              try {
                var keys2 = Object.keys(sessionStorage);
                for (var i = 0; i < keys2.length; i++) {
                  var v2 = sessionStorage.getItem(keys2[i]);
                  if (v2 && v2.indexOf('handoffLocation') !== -1 && v2.indexOf('modality') !== -1) {
                    return v2;
                  }
                }
              } catch(e) {}
              return '';
            })()
          `);
          if (lafData) console.log(`Captured LAF from storage (${lafData.length} chars)`);
          else console.log('No LAF found in storage either');
        } catch (e) {
          console.log('Storage fallback failed:', e.message);
        }
      }
    } else {
      console.log('Login window not available for LAF capture');
    }

    // Send to FastAPI backend
    const postData = JSON.stringify({ cookies: cookieStr, laf: lafData || '' });
    const result = await new Promise((resolve, reject) => {
      const req = http.request({
        hostname: '127.0.0.1',
        port: FASTAPI_PORT,
        path: '/api/atlas-cookies/electron',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(postData),
        },
      }, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
          try { resolve(JSON.parse(body)); }
          catch { resolve({ ok: false, message: body }); }
        });
      });
      req.on('error', reject);
      req.write(postData);
      req.end();
    });

    console.log('Cookie send result:', result);
    // Notify the main window to refresh cookie status
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('cookies-updated', result);
    }
    return result;

  } catch (err) {
    console.error('Cookie extraction failed:', err);
    return { ok: false, message: err.message };
  }
}

// ── Refresh cookies (re-extract from persistent session without opening login) ──
async function refreshCookies() {
  const krogerSession = session.fromPartition('persist:kroger');
  const allCookies = await krogerSession.cookies.get({ domain: KROGER_DOMAIN });

  if (!allCookies.length) {
    return { ok: false, message: 'No saved Kroger session. Please log in first.' };
  }

  const cookieStr = allCookies.map(c => `${c.name}=${c.value}`).join('; ');
  console.log(`Refreshed ${allCookies.length} cookies from persistent session`);

  const postData = JSON.stringify({ cookies: cookieStr });
  return new Promise((resolve, reject) => {
    const req = http.request({
      hostname: '127.0.0.1',
      port: FASTAPI_PORT,
      path: '/api/atlas-cookies/electron',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData),
      },
    }, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(body)); }
        catch { resolve({ ok: false }); }
      });
    });
    req.on('error', reject);
    req.write(postData);
    req.end();
  });
}

// ── IPC Handlers ──
ipcMain.handle('kroger:login', async () => {
  openLoginWindow();
  return { ok: true };
});

ipcMain.handle('kroger:extract-and-close', async () => {
  // Extract cookies + try to capture real LAF from the Kroger page
  const result = await extractAndSendCookies();
  if (loginWindow && !loginWindow.isDestroyed()) {
    loginWindow.close();
  }
  return result;
});

ipcMain.handle('kroger:refresh-cookies', async () => {
  return await refreshCookies();
});

ipcMain.handle('kroger:get-cookie-count', async () => {
  const krogerSession = session.fromPartition('persist:kroger');
  const cookies = await krogerSession.cookies.get({ domain: KROGER_DOMAIN });
  return { count: cookies.length };
});

ipcMain.handle('kroger:clear-session', async () => {
  const krogerSession = session.fromPartition('persist:kroger');
  await krogerSession.clearStorageData();
  return { ok: true };
});

// ── App lifecycle ──
app.whenReady().then(async () => {
  try {
    await startBackend();
    createMainWindow();

    // Auto-refresh cookies from persistent session on startup
    const result = await refreshCookies().catch(() => ({ ok: false }));
    if (result.ok && mainWindow) {
      mainWindow.webContents.on('did-finish-load', () => {
        mainWindow.webContents.send('cookies-updated', result);
      });
    }
  } catch (err) {
    console.error('Startup failed:', err);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  stopBackend();
  app.quit();
});

app.on('before-quit', () => {
  stopBackend();
});
