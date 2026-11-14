# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/juvenile454/hermes-circuit-bench/security/advisories/new) (repository
tab **Security → Report a vulnerability**). Do not open a public issue for them.

Include the Circuit Bench version (or commit), the Hermes version, your OS, what you did and what happened. Leave
out MAC addresses, serial numbers and other details of your own devices unless they are needed to reproduce the
problem. The maintainer aims to reply within seven days; fixes ship as a new release and a new pinned commit in the
Hermes plugin catalog.

## Supported versions

Only the latest release (currently 0.1.x) gets fixes.

## In scope

- A way to flash, erase or open a real serial port without the approvals and switches described below, or to make a
  `bench_board` handler for a real port or a PlatformIO build run without the approval hook having let that call
  through.
- A way to start PlatformIO (a build, or any call that runs a project's scripts) from the agent without Hermes
  asking (outside the documented `/yolo`, `hermes -z` and `approvals.mode: off` cases).
- Path traversal or writes outside `$HERMES_HOME/plugin-data/circuit-bench/`, the firmware folder you chose or the
  `out_dir` you named.
- The Desktop half reaching beyond the Hermes Desktop plugin SDK, or its backend routes answering without the app's
  session token.
- Wrong safety-relevant output, for example a missing low-voltage, laser or lithium-cell warning.

Out of scope: problems in Hermes itself, PlatformIO, esptool or the Espressif toolchains (report them upstream),
and the code of a firmware project you build: a build runs that project's scripts by design.

## Security model

1. Every agent build that starts PlatformIO, every real flash, and every board detection and monitor while **Ask
   before opening serial ports** is on (the default), goes through Hermes' approval; a `pre_tool_call` hook asks or
   blocks and never approves by itself. Cron jobs cannot run such builds, nor flash, detect or monitor real boards.
   The handlers of `bench_board` `detect`, `monitor` and `flash` on a real port, and of a `build` that starts
   PlatformIO, run only if the hook let exactly that call through for the same task, action and target; otherwise
   the tool answers `not_confirmed`. One hook pass serves one run, also when no question is asked. A port URL other than
   `sim://` (`rfc2217://`, `socket://` and the like) is blocked by the hook before the question for a detection,
   a monitor or a flash, also when **Ask before opening serial ports** is off. The record of a pass lives
   `approvals.timeout` + 60 s, kept between 120 and 3600 s (360 s when the setting is absent, unreadable or no number),
   and is held in memory only. The record is not a replacement for the other switches and refusals (**Allow flashing
   real boards**, **Access real hardware**, the cron block, the check for approvals that are off): they come first.
   The Bench's own routes do not use these records.
2. **Allow flashing real boards** is off by default; a flash copies every file it will write into a private folder
   `tmp/flash-<random>` in the plugin data folder (mode `0700`, files `0600`), checks the copies named `firmware.bin`,
   `bootloader.bin` and `partitions.bin` against the hashes recorded at build time, and writes the copies, not the
   build folder, to the detected board (port, MAC and the hash of the ELF are checked again by the tool; so are the
   images and the time of the last build: a build made after the question is not flashed: same ELF with other images
   or time ends with `not_confirmed`, another ELF with `elf_mismatch`). The folder is removed on every exit; a folder
   left behind by a process that was killed is removed by a later flash once it is older than an hour. Which files are
   covered by the check is limited; see "Known gaps".
3. **Access real hardware** off, or `CIRCUIT_BENCH_HW=off`, makes real ports unreachable; only `sim://` boards
   remain. When the plugin settings cannot be read from Hermes' configuration, real hardware and flashing stay off
   and port approval stays on (`hardware_access` and `allow_flash` `false`, `approve_serial` `true`); `/bench doctor`
   marks the check `settings` as `FAIL` (the Bench's doctor dialog shows it as a failed row) and agent calls for real
   boards end with `sim_only`.
4. The plugin makes no network calls, never updates itself, sends no telemetry and stores no credentials.
5. Low voltage only (3.3 V and 5 V logic, small DC loads); calculators refuse inputs above 60 V and no part of
   Circuit Bench covers mains wiring.
6. The approval question for a build or a flash names the checked values first (env, chip, MAC, port, ELF hash) and the
   firmware folder, the only free text, last and in quotes. Control characters, line breaks, Unicode direction marks,
   space variants other than U+0020, every `Default_Ignorable_Code_Point` (zero-width characters, variation selectors
   and others) and `"` are shown as `\uXXXX` (`\UXXXXXXXX` above U+FFFF) in the folder; the same characters are shown
   that way in env, MAC and port. In the folder every other quotation mark (the characters with the Unicode property
   `Quotation_Mark` except the apostrophe U+0027) and the characters that look like `"` (primes and a few others) are
   shown that way as well, so nothing in a folder name can look like the end of the quoted field; a folder `Lab’s`
   (U+2019) therefore appears as `Lab\u2019s`. The chip shows only its fixed name and revision, and the port of a flash,
   detection or monitor question only letters, digits and `._:/-` as they are. A path longer than 120 characters is
   shortened in the middle, also in its last part, so the shown path is never longer than 120 characters; the question
   then ends with ` (path shortened)`, which also appears when a character was only replaced. An env that is no
   PlatformIO name is refused before the question. The message and hint of an error answer and the message of a hook
   block show hidden characters in the same way (format and direction characters, line and paragraph separators, lone
   surrogates, DEL and C1 controls, `Default_Ignorable_Code_Point`); input is not refused for them. The list of
   characters is limited; see "Known gaps".

## Known gaps

- A session-scoped `/yolo` and one-shot runs (`hermes -z`, which bypass approvals by design) are not visible to
  plugins: there Hermes passes agent builds, flashes and port openings without asking. Keep **Allow flashing real
  boards** off while you use them. The full list is in the README sections "Safety" and "Disclosure".
- A flash checks images against the hashes recorded at build time only for files named `firmware.bin`,
  `bootloader.bin` and `partitions.bin`; `boot_app0.bin` from the framework package and extra images of a project are
  written as they were when copied. Hashes for the whole write list per flash address are not implemented.
- The check is bound to the file name, not to the flash address: a differently named file that a project's own
  `extra_scripts` or platform put at the bootloader offset is written unchecked, and the approved `bootloader.bin` is
  then only checked in place.
- The private copy is not protected against other processes of the same user (`0700`/`0600` keep out other users
  only), and the snapshot is taken after `pio project metadata`, which runs the project's `extra_scripts`. The ELF is
  hashed in place, not copied, and not written.
- Paths of the ELF and the images are normalised lexically: `a/link/..` is read as `a`.
- With readable settings that hold no entry for the plugin the defaults apply, including `hardware_access: true`; the
  safe values apply only when the settings cannot be read, and the health endpoint does not name that cause (the
  bench doctor does).
- Code in the same process that fakes the arguments of a tool call or calls the plugin's internals, for example
  another plugin, is not stopped by the approval binding, which holds per task, action and target, not per single
  call.
- That Hermes runs the hook before the handler and does not start the handler after a denial is an observation from
  Hermes' source and from probes against the tested versions, not a guarantee; the gateway and cron paths are derived
  from the source, not measured.
- A hook pass lives `approvals.timeout` + 60 s, at most 3600 s; with `approvals.timeout` above 3540 s, or an
  unreadable `config.yaml` (the plugin then assumes 300 s), a very late approval can end with `not_confirmed`; an
  unused pass stays in memory until it expires or the next pass of its task removes it.
- Hidden characters are shown by a fixed list, not by judgement. In questions: control, format, separator and space
  characters, lone surrogates and the blank Braille pattern; in messages to the model: format characters, line and
  paragraph separators, lone surrogates, DEL and C1 controls (spaces such as the no-break space stay); in both: every
  `Default_Ignorable_Code_Point` of Unicode 18.0.0. The folder of a question also shows the 30 code points of
  `Quotation_Mark` in Unicode 18.0.0, except the apostrophe U+0027, and 19 look-alikes of `"` (the primes and a few
  others) as escapes; the apostrophe stays as it is. Look-alike letters stay as they are, and a shortened path hides its
  middle part. Warnings, assumptions and serial lines are not filtered.
- Letters of right-to-left scripts (Hebrew, Arabic) in a folder name stay as they are and can change the displayed
  order of the path parts in a question. The quotation marks of the field stay at its two ends, and "always" of a
  build applies to the full, real folder path, not to the shown text.
- If the last build has no stored image hashes (it left no `firmware.bin`, `bootloader.bin` or `partitions.bin` next
  to the ELF, or the record is older), the images are not compared with hashes before they are written. The flash
  then checks only that `firmware.bin` is not older than the ELF (`elf_mismatch` otherwise), besides the ELF hash,
  the port and the MAC.
- Which characters are shown as escapes through their Unicode category (control, format, separator, space, lone
  surrogate) depends on the Unicode version of the Python that runs Hermes: a character that became a format
  character in a later version stays as it is on an older Python (Python 3.11 has Unicode 14.0). The lists
  `Default_Ignorable_Code_Point` and `Quotation_Mark` are fixed in the plugin (Unicode 18.0.0).
- A tool call without a task id never finds a stored approval record, so the handlers of `detect`, `monitor`, `flash`
  and of a build that starts PlatformIO answer `not_confirmed` (a refusal, the safe direction); the hook may still ask
  its question. Hermes passes a task id to hook and handler.
- Where the package `hermes_cli` cannot be imported (the core used as a library, for example in tests), there is no
  Hermes configuration to read and the default settings apply, including `hardware_access: true`. The safe values for
  unreadable settings apply where Hermes is present and its configuration cannot be read.
- The `summary` and `result` of a success answer return texts of the project (title, notes, names) as they are stored
  (your own data; emoji with a variation selector stay readable): hidden characters are not replaced there, only in
  questions, error answers and block messages.
- On an unreadable `config.yaml` the agent's serial monitor uses the same fallback values as Hermes (the last valid
  state) for the Hermes deadline, while the safety switches deliberately do not; the monitor's deadline cap applies
  only to the agent path, not to the Bench console.
