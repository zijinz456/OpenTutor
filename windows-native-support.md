# Windows native installation and startup support

This PR adds Windows packaging and process management. It does not change AI teaching prompts, layouts, grading, notes, or upstream Docker defaults. Both review PRs start independently from upstream main at `22e57bdd13a25cd394108578d1d398926263daef`.

## Supported targets and actual verification

| Item | Target / requirement | Actually checked |
| --- | --- | --- |
| Windows | Windows 10 22H2 x64 / Windows 11 x64 | Windows 11 23H2, OS build 22631.6199, x64 |
| Python | CPython 3.12 x64 for building from source; included in an installer | 3.12.14 |
| Node.js | 24.x x64 with npm for source setup; included in an installer | 24.21.0 |
| PowerShell | Windows PowerShell 5.1 | 5.1.22621.6133 |
| .NET Framework | 4.8+ for launcher / installer | Installed release key 533320 |
| Network | Needed to install source dependencies and use online model APIs | No paid model calls made during PR checks |

Windows 10, ARM64, Windows Server, and a separate clean physical PC have not been validated. The target compatibility range is not a claim that those systems passed testing. Microsoft's build mapping identifies build 22631 as Windows 11 23H2: https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information .

## Install from a fork or source ZIP

1. Install CPython 3.12 x64 and Node.js 24 x64 with npm. Use a writable folder. Keep any existing installation and private configuration separate.
2. Open PowerShell at this repository root. Verify `py -3.12 --version` and `node --version`.
3. Prepare the application:

```powershell
py -3.12 scripts/native-setup.py --check
py -3.12 scripts/native-setup.py
```

`--check` only verifies installed build tools. The second command copies the interpreter without global site-packages, creates the project virtual environment, installs the pinned Python dependencies, installs frontend dependencies, builds Next's standalone server and static assets, compiles the launcher, and creates private local configuration if missing. It downloads dependencies and the matching Node.js license; it does not ask for an API key. If Node is not on PATH, add `--node "C:/Program Files/nodejs/node.exe"`.

4. Double-click `OpenTutor.exe` or `Start-OpenTutor.cmd`, then open http://localhost:3001 . Select the provider / model and enter your own API key in Settings. Online models require network access and an appropriate account. Nothing in this PR provides a model subscription or model weights.

Alternative management commands:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/native-control.ps1 -Action Start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/native-control.ps1 -Action Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/native-control.ps1 -Action Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/native-control.ps1 -Action Backup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/native-control.ps1 -Action Clean
```

The API binds to 127.0.0.1:8000 and the web server to 127.0.0.1:3001. Startup refuses to terminate unrelated processes occupying those ports. Closing the page does not stop services; use the launcher or Stop command. Logs are owned by the services and archived per restart, rather than overwritten.

## Build and use a distributable installer

After native setup, Git is additionally required for the source/privacy allowlist:

```powershell
apps/api/.venv-win/Scripts/python.exe -X utf8 scripts/build-windows-package.py
```

The output `source-release/OpenTutor-Setup-1.2.0-win-x64.exe` includes CPython, Node.js, installed runtime dependencies, the standalone frontend, backend code, and third-party licenses. Binaries are build artifacts for a Release attachment, not files for this source PR. The bundled program reflects only this PR's upstream baseline; the separate teaching PR is not needed to install or start it.

For an end user: run the installer, choose a writable empty directory, install, then launch and configure their own API in Settings. They do not need to install Python, Node.js, Git, Docker, or WSL. The installer validates its payload hash, rejects unsafe archive paths, and refuses to overwrite a non-empty directory. It is not code-signed and does not support in-place upgrades. Back up and stop an older installation before installing to a new folder.

## Local data and safety boundaries

- `native-data/settings.env`: current user's model settings and per-install signing/encryption keys. Created once and preserved on repeat initialization.
- `native-data/data/opentutor.db`: local SQLite data; `native-data/uploads/`: imported files.
- `native-data/logs/`: active logs and restart archives; `local-backups/`: SQLite snapshot and full backup.
- `.runtime/`, `.venv-win/`, `node_modules/`, `.next/`, `OpenTutor.exe`, and `source-release/` are generated and excluded from ordinary source export.
- `CODE_SANDBOX_BACKEND=disabled` is explicit for native installs: it does not substitute unsafe host execution for Docker isolation. Existing non-Windows container/process policies remain opt-in behavior.
- `APP_AUTO_SEED_DEMO=false` skips the demo course while retaining system templates. The upstream default is unchanged unless configured.
- Full backups contain API settings and private data. Do not attach backups, real environment files, databases, imported courses, or classmates' work to a PR.

## Actual checks for this PR

On 2026-10-25, using this Windows-only overlay on the fixed upstream baseline:

- 20 targeted Python checks passed: first initialization, unique keys, preservation of existing settings, cleanup safety, demo seeding, code-execution platform/policy boundaries, whole-API import, and synthetic JWT round-trip. The lockfile includes upstream-required PyJWT 2.15.1; the prior local python-jose entry was replaced without reverting upstream authentication.
- Windows PowerShell restart-log archival check passed.
- Native setup `--check` passed with CPython 3.12.14 and Node.js 24.21.0. Full fresh internet installation using `native-setup.py` on another computer was not run; its component build/start flow was tested using isolated copies of the verified local dependencies.
- Standalone frontend production build passed without the teaching PR.
- PR-specific installer construction and new-directory extraction passed. With the upstream JWT dependency present, API/web/Settings returned HTTP 200; empty course/key state, synthetic API-setting persistence and verified SQLite/full backup passed. The final rebuilt installer, including PyJWT, passed a fresh-directory startup without manual dependency repairs, plus stop/start and synthetic-setting persistence. No live model-quality claim follows from these checks.

This documentation separates historical checks of the full customized app from checks repeated on this narrowly scoped PR. The full application's earlier 370 frontend tests are not claimed as tests of this isolated PR.
