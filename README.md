<p align="center">
  <img src="assets/mark.svg" width="72" height="72" alt="Saints Row Forge mark">
</p>

<div align="center">

# Saints Row Forge

**Receipted table mods for SRTT and SRIV. Game files stay read-only.**

An AI-operable modding workbench for **Saints Row: The Third** (PC) and
**Saints Row IV** (PC). Deterministic Python core, honest capability
reporting, machine-readable receipts.

<p>
  <a href="https://github.com/SenjuWoo/SaintsRowForge/actions/workflows/tests.yml"><img src="https://github.com/SenjuWoo/SaintsRowForge/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-c084fc?labelColor=140c1c" alt="MIT License"></a>
  <a href="https://github.com/SenjuWoo/SaintsRowForge/releases/latest"><img src="https://img.shields.io/github/v/release/SenjuWoo/SaintsRowForge?label=release&color=e8c547" alt="latest release"></a>
  <img src="https://img.shields.io/badge/python-%3E%3D3.10-c4a0e8?labelColor=140c1c" alt="Python 3.10+">
</p>

<p>
  <a href="#new-here-5-minutes">Quick start</a>
  ·
  <a href="#status-what-actually-works--all-verified-on-real-game-installs">Verified status</a>
  ·
  <a href="#mcp-server-no-dependencies">MCP</a>
  ·
  <a href="https://github.com/SenjuWoo/SaintsRowForge/releases">Releases</a>
</p>

</div>

<p align="center">
  <img src="assets/hero.svg" alt="Saints Row Forge verified on SRTT and SRIV" width="100%">
</p>

An AI-operable modding workbench for **Saints Row: The Third** (PC) and
**Saints Row IV** (PC). Deterministic Python core, honest capability
reporting, machine-readable receipts. Installable standalone; usable by any
MCP-capable agent (Hermes, Claude Desktop, Codex, ...) or directly via CLI.

## New here? (5 minutes)

**You need:** Windows 10/11 · [Python](https://www.python.org/downloads/) 3.10+ ·
Saints Row the Third and/or Saints Row IV (Steam PC).

1. Grab the zip from [Releases](https://github.com/SenjuWoo/SaintsRowForge/releases), unzip anywhere
2. Right-click `Install.ps1` → **Run with PowerShell** (no admin needed) — it installs to `%LOCALAPPDATA%\SaintsRowForge` and checks itself
3. Double-click `START-HERE.bat` any time you want status/help

Prefer git? Clone and run straight from source — same commands, just use
the repo's `src\srforge_cli.py` instead of the installed path.

### Your first mod — one weapon stat, fully receipted

```bat
set CLI=%LOCALAPPDATA%\SaintsRowForge\src\srforge_cli.py
python %CLI% doctor
python %CLI% mod new MyFirstMod --game sriv
```

Create `%LOCALAPPDATA%\SaintsRowForge\Workspaces\MyFirstMod\source\jobs\weapons.json`:

```json
{"operations": [
  {"operation": "multiply", "file": "weapons.xtbl",
   "record": "SMG-Storm", "field": "Magazine_Size", "value": 1.25}
]}
```

```bat
python %CLI% mod patch --workspace %LOCALAPPDATA%\SaintsRowForge\Workspaces\MyFirstMod
python %CLI% mod diff  --workspace %LOCALAPPDATA%\SaintsRowForge\Workspaces\MyFirstMod
python %CLI% mod build --workspace %LOCALAPPDATA%\SaintsRowForge\Workspaces\MyFirstMod
```

Done mod: `Workspaces\MyFirstMod\release\` — reopen-verified, SHA-256
receipted. Your game files were never touched.

### Installing your finished mod

The forge deliberately never writes your game directory. The built `.vpp_pc`
installs the same way as any other table mod for your game — current manual-install
guides are linked in [`knowledge/07-ONLINE-GUIDE-LINKS.md`](knowledge/07-ONLINE-GUIDE-LINKS.md).

### Got two mods that fight over the same table?

That's exactly what the merge engine is for:

```bat
python %CLI% merge --game sriv "C:\path\to\ModA" "C:\path\to\ModB"
```

Additions union, distinct edits all land, real conflicts get reported —
see the Merging section below.

`Update.ps1` / `Uninstall.ps1` ship alongside `Install.ps1`.

## Status (what actually works — all verified on real game installs)

| Area | SRTT | SRIV |
|---|---|---|
| Game detection + asset index | ✅ 21k files | ✅ 23k files |
| VPP packfiles | ✅ native v06 reader/writer | ✅ native v0A reader/writer |
| XTBL parse/query/patch/diff | ✅ | ✅ |
| ASM inspect/update (str2 sizes) | ✅ | ✅ byte-perfect round-trip vs vanilla |
| le_strings extract/build | ✅ | ✅ |
| Lua static lint | ✅ | ✅ |
| Cross-mod table **merge** (mod manager) | ✅ | ✅ |
| PEG/CPEG textures / meshes / audio / workshop | ❌ not implemented (reported `unsupported`) | ❌ not implemented (reported `unsupported`) |

### Merging mods (`srforge merge`)

Saints Row mods ship full copies of shared tables; installing two mods that
touch the same table normally means last-one-wins data loss. The forge
three-way merges every `.xtbl` against vanilla instead:

```bash
srforge merge --game sriv "path/to/ModA" "path/to/ModB"
```

- records added by either mod -> both survive
- distinct edits to different fields -> all applied
- two mods editing the same field -> **conflict logged** in
  `merge-report.json` (later-listed mod wins; every value is kept in the report)
- non-table file collisions (`.str2_pc`, `.asm_pc`, ...) -> flagged, later wins

Vanilla archives are **never written**; every build goes to a workspace.
The capability matrix (`srforge doctor`, `sr_capabilities`) is the source of
truth — statuses there always reflect what this build actually contains.

## Quickstart

```
python src\srforge_cli.py discover                 # find installed games
python src\srforge_cli.py doctor                   # full health report
python src\srforge_cli.py asset find weapons.xtbl --game sriv --json
python src\srforge_cli.py xtbl query --file weapons.xtbl \
    --record Pistol-Revolver --field Ragdoll_Force_Shoot --game sriv
python src\srforge_cli.py mod new MyMod --game sriv
# ... edit %LOCALAPPDATA%\SaintsRowForge\Workspaces\MyMod\source\jobs\*.json ...
python src\srforge_cli.py mod patch --workspace <path> --json
python src\srforge_cli.py mod diff  --workspace <path> --json   # semantic diff + scope guard
python src\srforge_cli.py mod build --workspace <path>          # package + receipt
```

Exit codes: `0` ok · `1` generic · `2` validation · `3` not-found ·
`4` dependency · `5` refused. `--json` works on every command.

## Example job file (`source/jobs/weapons.json`)

```json
{"operations": [
  {"operation": "set", "file": "weapons.xtbl",
   "record": "Pistol-Revolver", "field": "Ragdoll_Force_Shoot", "value": 450},
  {"operation": "multiply", "file": "weapons.xtbl",
   "record": "SMG-Storm", "field": "Magazine_Size", "value": 1.25}
]}
```

## MCP server (no dependencies)

```
python mcp_server\server.py        # stdio JSON-RPC; register with your client
```

13 typed tools: `sr_doctor sr_game_detect sr_capabilities sr_knowledge_search
sr_asset_search sr_asset_origin sr_asset_extract sr_xtbl_query sr_project_new
sr_mod_patch sr_mod_diff sr_mod_build sr_conflicts`.

`sr_knowledge_search` queries the additive `knowledge/` reference layer
(format notes, SDK adapter recipes, upstream source map with provenance).
It is evidence for research, never proof of a capability - the capability
matrix stays authoritative.

## Third-party tools

Never redistributed by this repo. Drop downloads into `%LOCALAPPDATA%\SaintsRowForge\Inbox`
(or `inbox/` in a checkout) and run `deps import`. Provenance (source URL +
SHA-256) is pinned in `tools_vault/manifest.json`; execution refuses
unregistered binaries. See THIRD-PARTY-NOTICES.md.

## Tests

```
python tests\run_tests.py          # 18 checks, no pytest needed, no game assets needed
```

Real-install validation is separate: doctor + the E2E flow above were run
against live Steam installs of both games.

## License

[MIT](LICENSE)

Saints Row is a trademark of its owners. This project is unofficial.
