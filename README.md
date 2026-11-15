# OpenTutor Guardian

A local-first Windows desktop agent for spaced study. It lives in the system tray, and during a study
session you started yourself it interrupts you every 10 to 25 minutes of real activity with a
5-question quiz.

The panel text is in Spanish, on purpose. This README is in English.

Derived from [OpenTutor](https://github.com/zijinz456/OpenTutor) (MIT). This repository keeps only the
desktop agent. The web app and API were removed on purpose: everything here runs on your machine.

## How to use it

1. Run the app (see Run below). A tray icon appears.
2. Open the panel and press "Iniciar estudio (60 min)". Nothing starts before you press it.
3. Study as usual. After 10 to 25 minutes of real activity a quiz of 5 questions appears.
   Four correct answers from a reviewed question source count as a certified pass.
4. Press Pause, End or Emergency at any time.

## What works today

- Tray icon with Open panel, Start session, Pause, End, Emergency, Exit. One instance per user.
- Closing the window hides it to the tray. If the tray icon cannot be created, closing exits.
- Opt-in sessions, study schedule and pending quiz survive a restart. Nothing starts by itself.
- Optional autostart, off by default, reversible, current user only.
- 5-question quiz from a local question bank first. Ollama (a program that runs language models on your
  own computer) is optional and used only when you pick it.
- Questions from an unreviewed source are always practice and never count as a certified pass.
- Panel tabs: Hoy, Tareas, Evidencia, Repasos, Progreso, Ajustes. Status uses icon and text, not only color.
- Practical tasks you write by hand (Tareas tab). Hand in a PowerPoint, Markdown or PDF file and a deterministic
  rubric checks it (Evidencia tab), followed by three short questions about your own file, called the defense. Safe reading: no macros, no
  active content, no rendering.

## What does not exist yet

No app or website blocking and no installer, so you run it from source. No link with FocoLocal, the author's
separate site limiter, so a validated task gives no leisure credit, meaning no permission for free time. PDF text cannot be read reliably, so a PDF with required terms goes to review.
See `docs/` for the usage guide, design notes and audits.

## Run (Windows PowerShell, from the repository root)

```
.\scripts\run-dev.ps1
.\scripts\run-dev.ps1 -Hidden
.\scripts\run-dev.ps1 -TestsOnly
```

`run-dev.ps1` is the way to run the app until an installer exists. It runs the tests, then starts the panel. `-Hidden` starts it in the tray only and
`-TestsOnly` runs the tests.

Requires Python 3.11 or newer with tkinter. The app has no third-party packages. No network except the
optional local Ollama at `127.0.0.1:11434`. No telemetry.

## Standard

This repository follows SVN11X/standards@v1. Install the development tools, then run the check from the
repository root:

```
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m unittest discover -s tests
```

Goals and non-goals are in `docs/goals.md`.

## Privacy and safety

Data stays in `%LOCALAPPDATA%\OpenTutorGuardian` (one SQLite file with results, session, tasks and evidence). Guardian does
not watch keys, screen, audio or window titles. The emergency button and Exit are always visible.

## License

MIT. See `LICENSE`.
