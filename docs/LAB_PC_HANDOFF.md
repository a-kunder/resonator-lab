# Continue development on the lab Windows computer

## Current project state

- Application version: 1.4.2. Canonical remote: https://github.com/a-kunder/resonator-lab.
- Supports ordered resonator batches with shared powers, per-resonator/per-power IFBW, editable room/cold attenuation and raw complex NPZ/CSV/JSON.
- Read-only LSCI log parser accepts spaced/no-space daily filenames and automatically follows new daily folders. User lab screenshot confirms successful temperature logging.
- Version 1.4.2 replaces rejected GRO sweep commands with documented Siglent TRIG:AVER native averaging. Local suite: 72 tests passed. Physical acquisition with this replacement still needs verification; see SIGLENT_ACQUISITION.md.
- Line D nominal losses: room temperature currently 20 dB (editable); cold 20 dB at 4 K + 3 dB at cold plate + 20 dB at MXC = 43 dB. Do not assume these for other lines. Instrument serial/resource addresses belong in local settings, not commits.
- LSCI Reader owns all Lake Shore control. Never open COM3 or enable historical direct PID prototypes. Physical automated temperature control and Qi/Qc fitting are not implemented.

## Local environment

Use a native Windows Codex environment with the same local Python/VISA installation used for acquisition. Add the actual cloned repository folder as the project. The virtual environment is local to that computer: `.venv\Scripts\python.exe`. Run `setup_windows.bat` if needed. Do not transfer a Mac virtual environment.

A ZIP folder is usable for local development, but cross-host Git handoff requires matching saved Git projects. Clone the repository on the lab PC and save that repository as a project on both hosts. Preserve existing lab data and local profiles outside any new checkout. Normal development tests must use fakes/simulators; only the lab user can authorize a physical measurement.

## Moving the conversation

The [official connection guide](https://learn.chatgpt.com/docs/remote-connections#hand-off-a-chat-between-hosts) describes connecting a destination host, saving matching repository projects, and selecting the chat footer's run location -> destination host -> Hand off. This transfers the chat/Git state. Availability depends on the installed app and rollout. Viewing a chat through a remote connection does not by itself move execution off its original host.

If handoff is unavailable, start a local Codex chat in this repository and use the context below. Conversation history is not stored in this Git repository; this is a working summary, not a copy of the chat.

## Starter prompt for a new local Codex chat

> Read AGENTS.md, PROJECT_MAP.json, docs/LAB_PC_HANDOFF.md, and docs/SIGLENT_ACQUISITION.md. Continue the resonator acquisition project on this Windows lab computer. First report the current branch/version, verify the local environment, and run the automated tests. LSCI Reader must retain ownership of COM3, PID, heaters and setpoints; temperatures come only from its existing logs. Do not initiate RF output or an actual sweep until I explicitly request that measurement. Commit completed software changes and push to the configured repository when access permits. The pending lab check is a first physical trace using the native averaging-trigger fix in v1.4.2; preserve calibration and saved raw complex data.

For installations and available Windows workflows, consult [official Windows documentation](https://learn.chatgpt.com/docs/windows/windows-app). Do not grant broad system access merely to troubleshoot VISA; use the app's normal permission flow for specific actions.
