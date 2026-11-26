# Changelog

## 0.2.4 - 2026-11-25

- Fixed: `SRFORGE_GAME_SRTT` / `SRFORGE_GAME_SRIV` now reach every CLI command. Before, only `discover` and `doctor` read them, so `asset`, `xtbl query --game`, `mod patch`, `mod build` and `merge` failed with SRF-GAME-002 ("installation not found") for any install outside a Steam library, even though the error's own hint said to set those variables. `discover` and `doctor` also gave one game's folder to both games, so setting only `SRFORGE_GAME_SRIV` made SRTT look installed at the SRIV path. Each variable now applies to its own game only, the same way the MCP server already did it.
- Added a regression test that drives the CLI (`discover`, `xtbl query`, `mod new`, `mod build`) with only `SRFORGE_GAME_SRIV` set (19 checks).
- README rebuilt: cover image, real screenshots from fixture runs, a commands table, install notes for the environment variables, the merge field granularity, and a note that `multiply` can write decimals into whole-number fields.
- Added this changelog.

## 0.2.3 - 2026-11-06

- `Install.ps1` and `Update.ps1` no longer mirror over the live install. The new code is staged beside it, the old code is moved to a timestamped backup, and a failed activation or a failing doctor restores the previous version and exits non-zero. Workspaces, Inbox, logs and tools_vault are never touched by the swap.
- `tests/Test-Installer.ps1` covers fresh install, data preservation, rollback and the uninstalled case, and runs in CI.

## 0.2.2 - 2026-08-22

- Cold-start fixes: `mod patch` extracts the tables it needs, like `mod build`; `mod new` creates `source/jobs`.

## 0.2.1 - 2026-08-22

- Installers replace code on update and ship the knowledge and scripts folders; README install section and five-minute new-user path.

## 0.2.0 - 2026-08-22

- Mod manager: cross-mod XTBL three-way merge (`merge`).
- Knowledge layer (`knowledge/`, `sr_knowledge_search`).

## 0.1.0 - 2026-08-22

- First public release: native VPP/ASM/XTBL/strings engines, transactional builds with receipts, CLI and dependency-free MCP server.
