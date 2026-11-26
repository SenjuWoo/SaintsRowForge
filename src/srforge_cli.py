"""srforge CLI - every MCP operation has a CLI equivalent here.

Exit codes: 0 ok, 1 generic, 2 validation, 3 not-found, 4 dependency, 5 refused.
--json on every command for machine consumption.
"""
import argparse
import json
import os
import shutil
import sys

# allow running from a checkout without install
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from srforge.core.receipts import ForgeError, ExitCode, new_receipt, save_receipt, sha256_file
from srforge.core import discovery, capabilities, modbuild, deps
from srforge.core.workspace import new_workspace, load_workspace, save_workspace_meta


FORGE_ROOT = None  # resolved lazily


def forge_root():
    global FORGE_ROOT
    if FORGE_ROOT:
        return FORGE_ROOT
    env = os.environ.get("SRFORGE_HOME")
    if env:
        FORGE_ROOT = env
        return FORGE_ROOT
    # default: %LOCALAPPDATA%/SaintsRowForge, fallback to package-relative
    la = os.environ.get("LOCALAPPDATA")
    cand = os.path.join(la, "SaintsRowForge") if la else None
    if cand and (os.path.isdir(cand) or _can_write(os.path.dirname(cand))):
        os.makedirs(cand, exist_ok=True)
        FORGE_ROOT = cand
        return FORGE_ROOT
    FORGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return FORGE_ROOT


def _can_write(d):
    try:
        os.makedirs(d, exist_ok=True)
        return True
    except OSError:
        return False


def _env_paths(game):
    """Per-game override from SRFORGE_GAME_<KEY>, matching the MCP server.
    Each game only ever sees its own variable, so setting SRFORGE_GAME_SRIV
    cannot make SRTT look installed."""
    v = os.environ.get(f"SRFORGE_GAME_{game.upper()}")
    return [v] if v else []


def _find(game):
    return discovery.find_game(game, _env_paths(game))


def _detect_all():
    found = {}
    for g in ("srtt", "sriv"):
        det = _find(g)
        if det:
            found[g] = det
    return found


def _index_for(game):
    from srforge.core.index import GameIndex
    det = _find(game)
    if not det:
        raise ForgeError("SRF-GAME-002",
                         f"{game} installation not found",
                         hint="set SRFORGE_GAME_SRTT / SRFORGE_GAME_SRIV env vars "
                              "to the install folder, or run srforge discover")
    return GameIndex(det["install_path"], game)


def _emit(data):
    print(json.dumps(data, indent=2, default=str))


def cmd_discover(args):
    found = _detect_all()
    if args.json:
        _emit({"games": found})
    else:
        for g, d in found.items():
            print(f"{g}: FOUND {d['install_path']} ({d['source']})")
        for g in ("srtt", "sriv"):
            if g not in found:
                print(f"{g}: not found")
    return ExitCode.OK


def cmd_doctor(args):
    report = {"games": {}, "tools": deps_status(), "capabilities": capabilities.snapshot()}
    found = _detect_all()
    for g in ("srtt", "sriv"):
        entry = {"found": g in found}
        if g in found:
            inst = found[g]["install_path"]
            entry["install_path"] = inst
            try:
                idx = _index_for(g)
                entry["asset_index"] = f"ready ({len(idx.resolved)} logical files)"
                entry["version"] = detect_version(inst)
            except ForgeError as e:
                entry["asset_index"] = f"error: {e.message}"
        caps = report["capabilities"].get(g, {})
        summary = {}
        for cap, meta in caps.items():
            base = cap.split(".")[0]
            summary.setdefault(base, []).append(meta["status"])
        entry["capability_summary"] = {k: sorted(set(v)) for k, v in summary.items()}
        report["games"][g] = entry
    if args.json:
        _emit(report)
    else:
        for g, e in report["games"].items():
            print(f"\n{g.upper()}")
            print(f"  Game: {'FOUND ' + e.get('install_path', '') if e['found'] else 'not found'}")
            if "version" in e:
                print(f"  Version hint: {e['version']}")
            print(f"  Asset index: {e.get('asset_index', 'n/a')}")
            for k, v in sorted(e.get("capability_summary", {}).items()):
                print(f"  {k}: {', '.join(v)}")
        print("\ntools:")
        for t, s in report["tools"].items():
            print(f"  {t}: {s}")
    return ExitCode.OK


def detect_version(install):
    exe = os.path.join(install, "saintsrowthewthird_dx11.exe")
    if os.path.isfile(exe):
        return "srtt_dx11"
    for c in ("saintsrowiv.exe", "saintsrow4.exe", "sriv_win32_final.exe"):
        p = os.path.join(install, c)
        if os.path.isfile(p):
            return c
    exes = [f for f in os.listdir(install) if f.lower().endswith(".exe")]
    return f"unknown (exes: {exes[:5]})"


def deps_status():
    vault = os.path.join(forge_root(), "tools_vault")
    mpath = os.path.join(vault, "manifest.json")
    status = {}
    try:
        with open(mpath, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except OSError:
        return {}
    for name, t in manifest.get("tools", {}).items():
        exe = os.path.join(t.get("dir", ""), t.get("exe", ""))
        ok = bool(t.get("source")) and os.path.isfile(exe)
        status[name] = "ready" if ok else "broken"
    return status


def cmd_asset(args):
    idx = _index_for(args.game)
    if args.op == "find":
        hits = []
        for name in idx.resolved:
            if args.pattern.lower() in name:
                hits.append(idx.find(name))
        if args.json:
            _emit({"matches": hits})
        else:
            for h in hits[:50]:
                print(f"{h['logical']:50} <- {os.path.basename(h['container'])} [{h['kind']}]")
        return ExitCode.OK
    name = getattr(args, "name", None) or getattr(args, "pattern", "")
    if args.op == "origin":
        _emit(idx.origin(name))
        return ExitCode.OK
    if args.op == "extract":
        ws = args.workspace
        load_workspace(ws)
        info = modbuild.extract_to(idx, name,
                                   os.path.join(ws, "extracted"))
        _emit(info)
        return ExitCode.OK
    raise ForgeError("SRF-CLI-001", f"unknown asset op {args.op}")


def cmd_xtbl(args):
    from srforge.formats.xtbl import Xtbl
    if args.op == "query":
        # resolve from vanilla archives when --game given; plain path otherwise
        if getattr(args, "game", None):
            import tempfile
            idx = _index_for(args.game)
            with tempfile.TemporaryDirectory() as td:
                modbuild.extract_to(idx, args.file, td)
                x = Xtbl.load(os.path.join(td, os.path.basename(args.file)))
                rec = x.find_record(args.record)
                el = x.get_field(args.record, args.field) if args.field else rec
                val = (el.text or "") if (args.field and el is not None) else None
                if rec is None:
                    raise ForgeError("SRF-XTBL-E04",
                                     f"record '{args.record}' not found in {args.file}")
                _emit({"record": args.record, "field": args.field, "value": val})
        else:
            x = Xtbl.load(args.file)
            rec = x.find_record(args.record)
            if not rec:
                raise ForgeError("SRF-XTBL-E04", f"record '{args.record}' not found in {args.file}")
            el = x.get_field(args.record, args.field) if args.field else rec
            _emit({"record": args.record,
                   "field": args.field,
                   "value": (el.text or "") if args.field else None})
        return ExitCode.OK
    raise ForgeError("SRF-CLI-001", f"use 'srforge mod patch' or jobs for edits")


def cmd_project(args):
    if args.op == "new":
        root = os.path.join(forge_root(), "Workspaces")
        ws = new_workspace(root, args.name, args.game)
        _emit({"workspace": ws})
        return ExitCode.OK
    if args.op == "validate":
        meta = load_workspace(args.path)
        problems = []
        jobs_dir = os.path.join(args.path, "source", "jobs")
        ops = modbuild.load_jobs(args.path)
        for op in ops:
            if not op.get("file"):
                problems.append(f"job missing file: {op}")
            if not op.get("operation"):
                problems.append(f"job missing operation: {op}")
        _emit({"workspace": args.path, "game": meta.get("game"),
               "operations": len(ops), "problems": problems})
        return ExitCode.VALIDATION if problems else ExitCode.OK
    raise ForgeError("SRF-CLI-001", f"unknown project op {args.op}")


def cmd_mod(args):
    if args.op == "new":
        root = os.path.join(forge_root(), "Workspaces")
        ws = new_workspace(root, args.name, getattr(args, "game", None))
        _emit({"workspace": ws})
        return ExitCode.OK

    if args.op == "extract":
        # convenience: extract all files named in jobs
        ws = args.workspace
        idx = _index_for(game_of(ws))
        ops = modbuild.load_jobs(ws)
        files = sorted({op["file"] for op in ops if op.get("file")})
        out = []
        for f in files:
            out.append(modbuild.extract_to(idx, f, os.path.join(ws, "extracted")))
        _emit({"extracted": out})
        return ExitCode.OK

    if args.op == "merge":
        return merge_flow(args)

    if args.op == "patch":
        ws = args.workspace
        ops = modbuild.load_jobs(ws)
        _ensure_extracted(ws, ops)
        results = modbuild.apply_ops(ops, os.path.join(ws, "extracted"),
                                     os.path.join(ws, "working"))
        _emit({"patched": len(results), "results": results})
        return ExitCode.OK

    if args.op == "diff":
        ws = args.workspace
        changes = modbuild.semantic_diff_report(
            os.path.join(ws, "extracted"), os.path.join(ws, "working"))
        ops = modbuild.load_jobs(ws)
        modbuild.guard_scope(ops, changes)
        write_diff_artifacts(ws, changes)
        _emit({"changed_fields": len(changes), "changes": changes})
        return ExitCode.OK

    if args.op == "build":
        return build_flow(args)

    raise ForgeError("SRF-CLI-001", f"unknown mod op {args.op}")


def game_of(ws):
    meta = load_workspace(ws)
    g = meta.get("game")
    if not g:
        raise ForgeError("SRF-WS-003", f"project.json has no game set")
    return g


def write_diff_artifacts(ws, changes):
    van = {"changed_files": sorted({c.get("file", "?") for c in changes}),
           "changes": changes}
    with open(os.path.join(ws, "vanilla-diff.json"), "w", encoding="utf-8") as f:
        json.dump(van, f, indent=2)
    lines = ["# Vanilla Diff", ""]
    for c in changes:
        if c["type"] == "field_changed":
            lines.append(f"- `{c['record']}` {c['field']}: {c['old']} -> {c['new']}")
        elif c["type"] == "record_added":
            lines.append(f"+ record added: {c['record']}")
        elif c["type"] == "record_removed":
            lines.append(f"- record removed: {c['record']}")
        else:
            lines.append(f"* {c}")
    open(os.path.join(ws, "vanilla-diff.md"), "w", encoding="utf-8").write("\n".join(lines))


def _ensure_extracted(ws, ops):
    """Extract any job-named files missing from extracted/ (shared by
    patch + build so the documented new->patch->diff->build order just
    works without a separate extract step)."""
    idx = None
    files = sorted({op["file"] for op in ops if op.get("file")})
    for f in files:
        dst = os.path.join(ws, "extracted", f)
        if not os.path.isfile(dst):
            if idx is None:
                idx = _index_for(game_of(ws))
            modbuild.extract_to(idx, f, os.path.join(ws, "extracted"))


def build_flow(args):
    ws = args.workspace
    game = game_of(ws)
    receipt = new_receipt(game, "mod.build", ws)
    idx = _index_for(game)
    ops = modbuild.load_jobs(ws)

    # 1. ensure extraction + patch are current
    files = sorted({op["file"] for op in ops if op.get("file")})
    _ensure_extracted(ws, ops)
    extracted = []
    for f in files:
        if os.path.isfile(os.path.join(ws, "extracted", f)):
            receipt["input_hashes"][f] = sha256_file(os.path.join(ws, "extracted", f))

    # 2. patch into working/ (record per-op old->new in the receipt)
    results = modbuild.apply_ops(ops, os.path.join(ws, "extracted"),
                                 os.path.join(ws, "working"))
    receipt["operations"] = [
        {"op": {k: v for k, v in r["op"].items() if not k.startswith("__")},
         "old": r.get("old"), "new": r.get("new")}
        for r in results
    ]

    # 3. semantic diff + scope guard
    changes = modbuild.semantic_diff_report(os.path.join(ws, "extracted"),
                                            os.path.join(ws, "working"))
    modbuild.guard_scope(ops, changes)
    write_diff_artifacts(ws, changes)

    # 4. build packages per patched file (vpp for tables; asm update optional)
    pkg_dir = os.path.join(ws, "package")
    os.makedirs(pkg_dir, exist_ok=True)
    built = []
    for f in files:
        src = os.path.join(ws, "working", f)
        out_vpp = os.path.join(pkg_dir, os.path.splitext(f)[0] + ".vpp_pc")
        built.append(modbuild.build_package(game, os.path.dirname(src),
                                            out_vpp, asm_update=None))
        receipt["output_hashes"][os.path.basename(out_vpp)] = built[-1]["sha256"]
    # stage release copy
    rel_dir = os.path.join(ws, "release")
    os.makedirs(rel_dir, exist_ok=True)
    staged = []
    for f in files:
        out_vpp = os.path.join(rel_dir, os.path.splitext(f)[0] + ".vpp_pc")
        shutil.copy2(os.path.join(pkg_dir, os.path.basename(out_vpp)), out_vpp)
        staged.append(out_vpp)

    # 5. receipts
    from srforge.core.receipts import finish_receipt, check as rcheck
    rcheck(receipt, "packages_reopened", all(b["entries"] for b in built),
           evidence="reopened")
    rcheck(receipt, "semantic_diff_scoped", True,
           detail=f"{len(changes)} changed fields across {len(files)} file(s)",
           evidence="syntax_validated")
    finish_receipt(receipt, "verified_static")
    path = save_receipt(receipt, os.path.join(ws, "receipts"))
    shutil.copy2(path, os.path.join(ws, "build-receipt.json"))
    _emit({"status": receipt["status"], "staged": staged,
           "changed_fields": len(changes), "receipt": path})
    return ExitCode.OK


def merge_flow(args):
    """Mod-manager core: union N mods' table edits into one installable pack."""
    from srforge.core import merger
    game = args.game
    idx = _index_for(game)
    mod_dirs = [os.path.abspath(d) for d in args.mods if os.path.isdir(d)]
    if not mod_dirs:
        raise ForgeError("SRF-MERGE-004", "no valid mod directories given")
    ws = new_workspace(os.path.join(forge_root(), "Workspaces"),
                       "merge-" + os.path.basename(mod_dirs[-1]), game)
    # 1. vanilla copies of every shared table (diff base)
    tables = merger.find_tables(mod_dirs)
    for fname in tables:
        f = os.path.basename(fname)
        dst = os.path.join(ws, "vanilla")
        os.makedirs(dst, exist_ok=True)
        modbuild.extract_to(idx, f, dst)
    # 2. merge
    report = merger.merge_tables(os.path.join(ws, "vanilla"), mod_dirs,
                                 os.path.join(ws, "working"))
    with open(os.path.join(ws, "merge-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    # 3. one pack per merged table
    pkg_dir = os.path.join(ws, "release")
    built = []
    for e in report:
        if not e.get("written"):
            continue
        out = os.path.join(pkg_dir, os.path.splitext(e["file"])[0] + ".vpp_pc")
        built.append({"file": e["file"], **modbuild.build_package(
            game, os.path.dirname(e["written"]), out, asm_update=None)})
        e["package"] = out
    _emit({"workspace": ws,
           "tables_merged": [e["file"] for e in report if e.get("written")],
           "conflicts": sum(len(e.get("conflicts", [])) for e in report),
           "additions": sum(len(e.get("additions", [])) for e in report),
           "packages": [b["sha256"][:12] for b in built],
           "report": os.path.join(ws, "merge-report.json")})
    return ExitCode.OK


def cmd_deps(args):
    inbox = os.path.join(forge_root(), "inbox")
    vault = os.path.join(forge_root(), "tools_vault")
    if args.op == "import":
        res = deps.import_inbox(inbox, vault)
        _emit(res)
        return ExitCode.OK
    if args.op == "status":
        _emit(deps_status())
        return ExitCode.OK
    raise ForgeError("SRF-CLI-001", f"unknown deps op {args.op}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="srforge")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("discover"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_discover)
    sp = sub.add_parser("doctor"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("asset"); sp.add_argument("--json", action="store_true")
    sp.add_argument("op", choices=["find", "origin", "extract"])
    sp.add_argument("pattern", nargs="?")
    sp.add_argument("--game", required=True)
    sp.add_argument("--name")
    sp.add_argument("--workspace")
    sp.set_defaults(func=cmd_asset)

    sp = sub.add_parser("xtbl"); sp.add_argument("--json", action="store_true")
    sp.add_argument("op", choices=["query"])
    sp.add_argument("--file", required=True)
    sp.add_argument("--record", required=True)
    sp.add_argument("--field")
    sp.add_argument("--game")  # resolve --file from vanilla archives when set
    sp.set_defaults(func=cmd_xtbl)

    sp = sub.add_parser("project"); sp.add_argument("--json", action="store_true")
    sp.add_argument("op", choices=["new", "validate"])
    sp.add_argument("name_or_path")
    sp.add_argument("--game")
    sp.set_defaults(func=cmd_project)

    sp = sub.add_parser("mod"); sp.add_argument("--json", action="store_true")
    sp.add_argument("op", choices=["new", "extract", "patch", "diff", "build"])
    sp.add_argument("name", nargs="?")
    sp.add_argument("--workspace")
    sp.add_argument("--game")
    sp.set_defaults(func=cmd_mod)

    sp = sub.add_parser("merge"); sp.add_argument("--json", action="store_true")
    sp.add_argument("--game", required=True)
    sp.add_argument("mods", nargs="+")
    sp.set_defaults(func=merge_flow)

    sp = sub.add_parser("deps"); sp.add_argument("--json", action="store_true")
    sp.add_argument("op", choices=["import", "status"])
    sp.set_defaults(func=cmd_deps)

    args = p.parse_args(argv)
    # normalize project arg
    if args.cmd == "project":
        if args.op == "new":
            args.name = args.name_or_path
        else:
            args.path = args.name_or_path
    # mod: 'new NAME' vs '--workspace PATH' both resolve to args.workspace
    if args.cmd == "mod" and getattr(args, "workspace", None) is None:
        args.workspace = getattr(args, "name", None)
    try:
        rc = args.func(args)
        return rc
    except ForgeError as e:
        err = {"error": {"code": e.code, "message": e.message, "hint": e.hint}}
        if "--json" in (argv or sys.argv[1:]):
            print(json.dumps(err, indent=2))
        else:
            print(f"\n{e.code}\n\n{e.message}\n", file=sys.stderr)
            if e.hint:
                print(f"Hint: {e.hint}", file=sys.stderr)
        codes = {"SRF-GAME": 3, "SRF-IDX": 3, "SRF-XTBL": 2, "SRF-DIFF": 2,
                 "SRF-JOB": 2, "SRF-PKG": 2, "SRF-CAP": 5}
        prefix = e.code.split("-")[1]
        return next((v for k, v in codes.items() if e.code.startswith(k)), 1)
    except FileNotFoundError as e:
        print(f"SRF-DEP-001 dependency/file missing: {e}", file=sys.stderr)
        return ExitCode.DEPENDENCY


if __name__ == "__main__":
    sys.exit(main())
