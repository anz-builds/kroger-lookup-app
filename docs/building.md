# Building the desktop app

The desktop app is two parts:

- the Python backend, bundled into one folder with PyInstaller (`backend/dist/backend/`)
- the Electron app, which electron-builder packages with that folder inside it (`resources/backend/`)

The build scripts do both steps. Neither bundles your credentials: the packaged app asks for them on first launch.

## Windows

Run from the repository root:

```
build.bat
```

The output is `electron\dist\KrogerPriceLookup-<version>-portable.exe`, a single portable file of about 190 MB. It needs no installation.

## macOS (Apple Silicon)

Run from the repository root, on a Mac:

```
./build.sh
```

The output is `electron/dist/KrogerPriceLookup-<version>-arm64.dmg`. The app is ad-hoc signed, not signed and notarized with an Apple Developer ID, so when it comes from another computer or a download, macOS says it "could not verify" the app and won't open it. To open it the first time on macOS 15 (Sequoia) or later:

1. Drag the app from the `.dmg` to Applications, then double-click it. When the warning appears, click **Done**.
2. Open **System Settings > Privacy & Security**, scroll to **Security**, and click **Open Anyway** next to the app's name. The button appears only after a blocked launch, for about an hour.
3. Confirm with your password or Touch ID, then click **Open Anyway** again.

macOS remembers the choice. Right-clicking the app and choosing **Open** no longer skips this check on macOS 15 and later.

PyInstaller can only build for the system it runs on, so the macOS app has to be built on a Mac.

## Linux (x64)

Run from the repository root, on Linux:

```
./build.sh
```

The output is `electron/dist/KrogerPriceLookup-<version>-x86_64.AppImage`. To run it, make it executable with `chmod +x`, then open it.

AppImages need the FUSE 2 library. Ubuntu 22.04 and later don't install it by default, so the app stops with `dlopen(): error loading libfuse.so.2`. Install it once (Ubuntu 24.04 package name):

```
sudo apt install libfuse2t64
```

On Ubuntu 22.04 the package is `libfuse2`. Without installing anything, you can also run the app with `./KrogerPriceLookup-<version>-x86_64.AppImage --appimage-extract-and-run`. This also works in WSL on Windows.

## Release builds on GitHub

`.github/workflows/release.yml` builds all three apps on GitHub's own Windows, macOS and Linux machines, then creates a GitHub release with the three files. It runs when you push a version tag:

```
git tag v<version>
git push origin v<version>
```

The tag has to match the version in `electron/package.json`, or the workflow stops.

## Version number

The version comes from `electron/package.json`. Change it there before a release; the output file names follow it.

## Publishing a release

Push a version tag (see "Release builds on GitHub" above); the workflow publishes the Windows `.exe`, the macOS `.dmg` and the Linux `.AppImage` to the release. The web app's "Download Desktop App" link points to the Releases page.

## Changing dependencies

Python dependencies are declared in `backend/pyproject.toml` with exact versions. After any change, regenerate both hashed lock files from the repository root (this needs uv):

```
uv pip compile backend/pyproject.toml --universal --python-version 3.13 --generate-hashes -o backend/requirements.txt
uv pip compile backend/pyproject.toml --extra dev --universal --python-version 3.13 --generate-hashes -o backend/requirements-dev.txt
```

`--universal` makes one lock file that works on Windows, macOS and Linux. The hashes make pip reject any package file that doesn't match.

Electron and electron-builder are pinned to exact versions in `electron/package.json`.
