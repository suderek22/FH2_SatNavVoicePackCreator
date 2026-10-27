# SatNav Voice pack creator

A tool for building custom SatNav (Anna) voice packs for Forza Horizon 2 with the FH2 Mod Platform.
It includes the SatNavVoice loader (`SatNavVoice.dll` v1.1.1) and ffmpeg - nothing else to install.

## Requirements
- Forza Horizon 2 (`Anthem_1.0.0.64_x64__8wekyb3d8bbwe`) with the FH2 Mod Platform and an `fh2-mods` folder
- Forza Horizon 2 Extra Options (required by the FH2 Mod Platform)

## First start
Pick the game folder (its name must be `Anthem_1.0.0.64_x64__8wekyb3d8bbwe` and it must contain `Mount`) and
your `fh2-mods` folder. You can change them later with **Game folders**.

## Using it
1. **New voice pack** - choose a name and the game language whose SatNav bank you want to replace.
   The stock sounds of that language are exported automatically the first time.
2. In the list, press **Attach file...** under any line to assign your own `.mp3`, `.wav` or `.ogg`.
   Press the play buttons to hear the stock sound and your file. Lines left empty keep the game's original sound.
   Colours: blue = Imperial, red = Metric, yellow = Various. The line
   `HZ2_VO_ANNA_SatNav_Imperial_Destination_Default_1` (info mark) is used for both Imperial and Metric.
3. **BUILD** converts, trims and level-matches your files to the game's format and creates the bank.
   Lines that are longer than the stock ones are marked - test them in the game.
4. **INSTALL** copies `SatNavVoice.dll`, `SatNavVoice.ini` (only if missing) and `SatNav\HZ2_DX_SatNav_XX.bank`
   into `fh2-mods`. Close the game first, then set the game's speech language to the pack language.
5. **Export pack (.zip)** saves the built mod plus the project so it can be shared or imported again.
6. **REMOVE** deletes the pack from the tool (asks for confirmation). Files already installed in `fh2-mods` are not touched.

**Save** (Ctrl+S) stores the project as a single `.svpack` file in the `data\packs` folder next to the exe.
**Import pack (.zip)** loads a pack exported by this tool.

## How to tab / README button
The **How to** tab has a short step-by-step guide. The **README** button (top right) opens this file.

## Console tab
A read-only log of everything the tool does (stock export, every build step per line, install, errors). Use **Copy all** to share it.

## Stock sounds tab / Load stock .bank
Exports every sound of a stock game bank to WAV files with a `list.csv` into `data\stock\<LANG>` next to the exe,
where you can browse and play them.

## Data
Everything the tool creates is kept in the `data` folder next to the exe (stock sounds, projects, builds, `error.log`).
