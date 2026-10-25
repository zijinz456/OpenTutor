# feat(windows): add native startup and a self-contained installer

Windows users gain a source-setup helper, EXE launcher, status/stop/backup/cleanup controls, restart-safe logs, and a self-contained installer. Services bind only to loopback. Each install creates its own private settings and blank course data; code execution is explicitly disabled instead of substituting an insecure host sandbox.

Scope: runtime preparation, pinned dependencies including upstream-required PyJWT 2.15.1, standalone Next build, launcher/installer source, demo-seeding switch, privacy ignores, tests and documentation. No teaching prompt, notebook, UI redesign, grading or knowledge-graph removal changes. Existing shared and Docker defaults are retained.

## Versions and installation

Target: Windows 10 22H2 x64 / Windows 11 x64. Actual host: Windows 11 23H2 build 22631.6199, CPython 3.12.14, Node.js 24.21.0, Windows PowerShell 5.1.22621.6133 and .NET release key 533320 (4.8+ required). Windows 10, ARM64 and a separate clean physical PC were not tested.

Source setup: install CPython 3.12 x64 and Node.js 24 x64 with npm, run `py -3.12 scripts/native-setup.py --check`, then `py -3.12 scripts/native-setup.py`. Start `OpenTutor.exe` or `Start-OpenTutor.cmd`; configure the user's model/API in Settings. A built installer includes the runtimes and requires neither Docker nor separately installed Python/Node. Detailed startup, stop, backup, build and upgrade steps: [Windows guide](docs/guides/windows-native-support.md).

## Validation

20 targeted Python checks, the PowerShell log-archive check, native setup --check, standalone production build, PR-specific installer construction/extraction and independent local startup passed. Runtime checks cover empty courses/keys, HTTP 200 for API/web/Settings, synthetic configuration persistence, restart and verified backup. Full fresh internet setup on another computer was not tested; no live model-quality claim is made.

No EXE, runtime binaries, API keys, account credentials, databases, logs, backups, real imports or classmate data are committed. Built installers belong in Release attachments. Tests use isolated directories and synthetic values.

Base: upstream main `22e57bdd13a25cd394108578d1d398926263daef`. Independent of the teaching PR. Prior checks of the full customized app are not represented as tests of this narrow PR.
