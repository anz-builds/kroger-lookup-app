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

The output is `electron/dist/KrogerPriceLookup-<version>-arm64.dmg`. The app is ad-hoc signed, not signed with an Apple Developer certificate. If you copy it from another computer, right-click the app and choose **Open** the first time.

PyInstaller can only build for the system it runs on, so the macOS app has to be built on a Mac.

## Linux (x64)

Run from the repository root, on Linux:

```
./build.sh
```

The output is `electron/dist/KrogerPriceLookup-<version>-x86_64.AppImage`. To run it, make it executable with `chmod +x`, then open it.

## Release builds on GitHub

`.github/workflows/release.yml` builds all three apps on GitHub's own Windows, macOS and Linux machines, then creates a GitHub release with the three files. It runs when you push a version tag:

```
git tag v<version>
git push github v<version>
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
