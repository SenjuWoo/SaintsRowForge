"""Full test suite: format round-trips, precedence, failure paths, E2E flow.
Run: python tests/run_tests.py   (no pytest dependency needed)
"""
import json
import os
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from srforge.formats import vpp, xtbl as xtbl_mod, strings, asm as asm_mod
from srforge.formats.crc import crc_volition
from fixtures import make_fixture_game, make_xtbl, make_asm

PASS = []
FAIL = []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  ok  {name}")
    except Exception as e:
        import traceback
        FAIL.append((name, e))
        print(f" FAIL {name}: {e}")
        traceback.print_exc()


# ---------- vpp ----------

def t_vpp_roundtrip_plain():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "a.vpp_pc")
    files = {"one.xtbl": b"<root/>", "dir/two.lua": b"-- hi"}
    vpp.write_packfile(p, files, condensed=False, compressed=False)
    pf = vpp.Packfile.from_file(p)
    got = {e.name: pf.read_entry(e) for e in pf.files()}
    assert got == {"one.xtbl": b"<root/>", "dir/two.lua": b"-- hi"}, got


def t_vpp_roundtrip_condensed_compressed():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "b.vpp_pc")
    payload = (b"AAA" * 4000)  # compressible
    vpp.write_packfile(p, {"x.bin": payload}, condensed=True, compressed=True)
    pf = vpp.Packfile.from_file(p)
    assert pf.is_compressed and pf.is_condensed
    assert pf.get("x.bin") == payload


def t_vpp_str2_style():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "c.str2_pc")
    files = list({f"{i:02}.casm_pc": bytes([i]) * 100 for i in range(5)}.items())
    vpp.write_packfile(p, files, condensed=True, compressed=True)
    pf = vpp.Packfile.from_file(p)
    for n, data in files:
        assert pf.get(n) == data


def t_vpp_header_checksum():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "d.vpp_pc")
    vpp.write_packfile(p, {"f": b"data"}, condensed=False, compressed=False)
    raw = open(p, "rb").read()
    desc, ver, csum = struct.unpack_from("<III", raw, 0)
    assert desc == 0x51890ACE and ver == 0x0A
    calc = crc_volition(raw[0x0C:0x28])
    assert csum == calc, (hex(csum), hex(calc))


def t_vpp_rejects_garbage():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "bad.vpp_pc")
    open(p, "wb").write(b"\x00" * 64)
    try:
        vpp.Packfile.from_file(p)
        raise AssertionError("should have raised")
    except ValueError:
        pass


# ---------- xtbl ----------

XT_A = make_xtbl([("Gun", {"Weapon": {"Damage": "85", "Impulse": "240"}})])
XT_B = make_xtbl([("Gun", {"Weapon": {"Damage": "106.25", "Impulse": "420"}})])


def t_xtbl_diff_semantic():
    changes = xtbl_mod.semantic_diff(xtbl_mod.Xtbl(XT_A), xtbl_mod.Xtbl(XT_B))
    fc = [c for c in changes if c["type"] == "field_changed"]
    assert {(c["field"], c["old"], c["new"]) for c in fc} == \
           {("Weapon/Damage", "85", "106.25"), ("Weapon/Impulse", "240", "420")}, changes


def t_xtbl_duplicate_detection():
    dup = make_xtbl([("A", {"V": "1"}), ("B", {"V": "2"}), ("A", {"V": "3"})])
    probs = xtbl_mod.Xtbl(dup).validate()
    assert any("duplicate" in p["message"] for p in probs), probs


def t_xtbl_missing_record_fails():
    x = xtbl_mod.Xtbl(XT_A)
    try:
        x.set_field("Nope", "Weapon/Damage", 1)
        raise AssertionError("should raise")
    except KeyError:
        pass


# ---------- strings ----------

def t_strings_roundtrip():
    s = strings.StringsFile()
    s.strings[1] = "alpha"
    s.strings[2] = ""
    s.strings[crc_volition("beta")] = "beta text"
    back = strings.StringsFile.parse(s.to_bytes())
    assert back.strings == s.strings


# ---------- asm ----------

def t_asm_parse_0c_and_update():
    d = tempfile.mkdtemp()
    s2 = os.path.join(d, "mycont.str2_pc")
    vpp.write_packfile(s2, {"01.casm_pc": b"x" * 32}, condensed=True, compressed=True,
                       is_str2=True)
    a = make_asm(0x0C, [("mycont.str2_pc", 0x05)])
    ap = os.path.join(d, "test.asm_pc")
    open(ap, "wb").write(a)
    af = asm_mod.AsmFile.parse(a)
    assert af.version == 0x0C and af.containers[0].name == "mycont.str2_pc"
    before = af.containers[0].packfile_base_offset
    c = af.update_container_sizes(s2)
    assert c is not None
    af2 = asm_mod.AsmFile.parse(af.to_bytes())
    c = af2.containers[0]
    prim = c.primitives[0]
    # cpu_size = uncompressed payload size of the single entry (32 bytes)
    assert prim.cpu_size == 32, prim.cpu_size
    assert af.containers[0].packfile_base_offset > 0


def t_asm_missing_container_is_none():
    a = make_asm(0x0C, [("other.str2_pc", 0x05)])
    af = asm_mod.AsmFile.parse(a)
    fake_s2 = os.path.join(tempfile.mkdtemp(), "zzz.str2_pc")
    open(fake_s2, "wb").write(b"junk")
    assert af.update_container_sizes(fake_s2) is None


def t_asm_version_0b_smaller():
    """0x0B parses; 0x0C containers are exactly one byte larger each."""
    b = make_asm(0x0B, [("x.str2_pc", 1)])
    c = make_asm(0x0C, [("x.str2_pc", 1)])
    afb = asm_mod.AsmFile.parse(b)
    assert afb.version == 0x0B
    assert len(c) - len(b) == 1  # the CompressionType byte


# ---------- index / precedence ----------

def t_precedence_patch_wins():
    root = tempfile.mkdtemp(prefix="srfidx_")
    gdir = make_fixture_game(root)
    from srforge.core.index import GameIndex
    idx = GameIndex(gdir, "sriv")
    hit = idx.find("weapons.xtbl")
    assert hit["kind"] == "vpp" and hit["container"].endswith("patch_compressed.vpp_pc"), hit
    origins = idx.origin("weapons.xtbl")
    assert len(origins) >= 2 and origins[0]["wins"] and not origins[1]["wins"]
    # winner content is the PATCHED row set (SMG damage 33)
    from srforge.formats.vpp import Packfile
    pf = Packfile.from_file(hit["container"])
    data = pf.get("weapons.xtbl").decode()
    assert "<Clip_Size>45</Clip_Size>" in data


def t_index_missing_file_error():
    root = tempfile.mkdtemp()
    gdir = make_fixture_game(root)
    from srforge.core.index import GameIndex
    idx = GameIndex(gdir, "sriv")
    try:
        idx.find("nonexistent.xtbl")
        raise AssertionError("should raise ForgeError")
    except Exception as e:
        assert "SRF-IDX-001" in str(getattr(e, 'code', '')) or "not found" in str(e)


# ---------- modbuild E2E on synthetic game ----------

def _mk_workspace(ws_root, game_dir, game):
    from srforge.core.workspace import new_workspace
    ws = new_workspace(ws_root, "TestMod", game)
    return ws


def t_e2e_extract_patch_build_diff_receipt():
    root = tempfile.mkdtemp(prefix="srfe2e_")
    gdir = make_fixture_game(root)
    ws_root = os.path.join(root, "workspaces")

    # point discovery at fixture via env
    os.environ["SRFORGE_GAME_SRIV"] = gdir
    try:
        import importlib
        from srforge.core import discovery
        importlib.reload(discovery)
        from srforge.core import modbuild
        from srforge.core.index import GameIndex

        ws = _mk_workspace(ws_root, gdir, "sriv")
        jobs = [{"operation": "multiply", "file": "weapons.xtbl",
                 "record": "Pump Shotgun", "field": "Weapon/Impulse",
                 "value": 2.0}]
        jf = os.path.join(ws, "source", "jobs")
        os.makedirs(jf, exist_ok=True)
        json.dump(jobs, open(os.path.join(jf, "main.json"), "w"))

        idx = GameIndex(gdir, "sriv")
        info = modbuild.extract_to(idx, "weapons.xtbl", os.path.join(ws, "extracted"))
        assert info["precedence_order"] == max(
            o for _n, _c, o in [(h["logical"], h["container"], h["precedence_order"])
                                for h in [idx.find("weapons.xtbl")]])

        results = modbuild.apply_ops(jobs, os.path.join(ws, "extracted"),
                                     os.path.join(ws, "working"))
        assert results[0]["old"] == "240" and results[0]["new"] == "480", results

        changes = modbuild.semantic_diff_report(os.path.join(ws, "extracted"),
                                                os.path.join(ws, "working"))
        fields_changed = {c["field"]: c for c in changes if c["type"] == "field_changed"}
        assert set(fields_changed) == {"Weapon/Impulse"}, fields_changed
        modbuild.guard_scope(jobs, changes)

        out = os.path.join(ws, "package", "weapons.vpp_pc")
        built = modbuild.build_package("sriv", os.path.join(ws, "working"), out)
        assert os.path.isfile(out)
        pf = vpp.Packfile.from_file(out)
        assert [e.name for e in pf.files()] == ["weapons.xtbl"]
        reopened = pf.get("weapons.xtbl").decode()
        assert "<Impulse>480</Impulse>" in reopened
    finally:
        os.environ.pop("SRFORGE_GAME_SRIV", None)


def t_scope_guard_fails_on_unexpected():
    from srforge.core.modbuild import guard_scope
    from srforge.core.receipts import ForgeError
    ops = [{"operation": "multiply", "file": "w.xtbl", "record": "Pump Shotgun",
            "field": "Weapon/Damage", "value": 1.25}]
    changes = [{"type": "field_changed", "record": "Totally Other", "field": "X",
                "old": "1", "new": "2"}]
    try:
        guard_scope(ops, changes)
        raise AssertionError("guard should have failed")
    except ForgeError as e:
        assert "SRF-DIFF-001" in e.code


def t_merge_union_and_conflict():
    """Cross-mod table merge: additions union, distinct edits coexist,
    same-field conflicts logged (later wins), vanilla never touched."""
    import tempfile
    from srforge.core import merger
    from srforge.formats.xtbl import Xtbl

    def _mk(path, records):
        body = "".join(
            f"<Record><Name>{n}</Name><Damage>{d}</Damage></Record>"
            for n, d in records)
        open(path, "w", encoding="utf-8").write(
            f"<Table><Records>{body}</Records></Table>")
        return Xtbl.load(path)

    with tempfile.TemporaryDirectory() as td:
        van = os.path.join(td, "vanilla"); os.makedirs(van)
        m1 = os.path.join(td, "modA"); os.makedirs(m1)
        m2 = os.path.join(td, "modB"); os.makedirs(m2)
        _mk(os.path.join(van, "weapons.xtbl"),
            [("Base", 10), ("Shared", 20)])
        _mk(os.path.join(m1, "weapons.xtbl"),
            [("Base", 15), ("Shared", 22), ("ModA_Gun", 99)])
        _mk(os.path.join(m2, "weapons.xtbl"),
            [("Shared", 25), ("ModB_Gun", 77), ("Base", 12)])

        out = os.path.join(td, "out")
        rep = merger.merge_tables(van, [m1, m2], out)
        merged = Xtbl.load(os.path.join(out, "weapons.xtbl"))
        names = {r.find("Name").text for r in merged.records()}
        assert names == {"Base", "Shared", "ModA_Gun", "ModB_Gun"}, names
        g = lambda n, f: merged.get_field(n, f).text
        assert g("Base", "Damage") == "12"      # A then B edited -> conflict, later wins
        assert g("Shared", "Damage") == "25"    # conflict -> later mod wins
        e = rep[0]
        assert len(e["conflicts"]) >= 2 and any(
            c["record"] == "Shared" for c in e["conflicts"])
        assert any("+ModA_Gun" in a for a in e["additions"])
        assert any("+ModB_Gun" in a for a in e["additions"])

    print("ok t_merge_union_and_conflict")


def t_malformed_job_rejected():
    from srforge.core import modbuild
    root = tempfile.mkdtemp(prefix="srfbad_")
    gdir = make_fixture_game(root)
    ws = os.path.join(root, "ws")
    os.makedirs(os.path.join(ws, "source", "jobs"), exist_ok=True)
    os.makedirs(os.path.join(ws, "extracted"), exist_ok=True)
    json.dump([{"operation": "multiply", "file": "weapons.xtbl",
                "record": "Ghost Gun", "field": "Damage", "value": 2}],
              open(os.path.join(ws, "source", "jobs", "j.json"), "w"))
    from srforge.core.receipts import ForgeError
    try:
        modbuild.apply_ops([{"operation": "multiply", "file": "weapons.xtbl",
                             "record": "Ghost Gun", "field": "Damage", "value": 2}],
                           os.path.join(ws, "extracted"),
                           os.path.join(ws, "working"))
        raise AssertionError("missing extraction should fail")
    except ForgeError as e:
        assert e.code == "SRF-JOB-002", e.code


def t_cli_env_override_per_game():
    """SRFORGE_GAME_SRIV must reach every CLI command (not just discover) and
    must not make SRTT look installed at the SRIV path."""
    import contextlib
    import io
    import srforge_cli
    root = tempfile.mkdtemp(prefix="srfcli_")
    gdir = make_fixture_game(root)
    saved = {k: os.environ.get(k) for k in
             ("SRFORGE_GAME_SRIV", "SRFORGE_GAME_SRTT", "SRFORGE_HOME")}
    os.environ["SRFORGE_GAME_SRIV"] = gdir
    os.environ.pop("SRFORGE_GAME_SRTT", None)
    os.environ["SRFORGE_HOME"] = os.path.join(root, "home")
    srforge_cli.FORGE_ROOT = None

    def run(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = srforge_cli.main(argv)
        return rc, buf.getvalue()

    norm = lambda p: os.path.normcase(os.path.normpath(p))
    try:
        rc, out = run(["discover", "--json"])
        games = json.loads(out)["games"]
        assert rc == 0 and norm(games["sriv"]["install_path"]) == norm(gdir), games
        # a real Steam SRTT may exist on a dev box; it must never be the SRIV fixture
        if "srtt" in games:
            assert norm(games["srtt"]["install_path"]) != norm(gdir), games

        rc, out = run(["xtbl", "query", "--file", "weapons.xtbl", "--record", "SMG",
                       "--field", "Weapon/Damage", "--game", "sriv", "--json"])
        assert rc == 0 and json.loads(out)["value"] == "33", (rc, out)  # patch vpp wins

        rc, out = run(["mod", "new", "EnvMod", "--game", "sriv", "--json"])
        ws = json.loads(out)["workspace"]
        jobs = os.path.join(ws, "source", "jobs")
        os.makedirs(jobs, exist_ok=True)
        with open(os.path.join(jobs, "w.json"), "w", encoding="utf-8") as fh:
            json.dump({"operations": [{"operation": "set", "file": "weapons.xtbl",
                                       "record": "SMG", "field": "Weapon/Damage",
                                       "value": 50}]}, fh)
        rc, out = run(["mod", "build", "--workspace", ws, "--json"])
        res = json.loads(out)
        assert rc == 0 and res["changed_fields"] == 1, (rc, out)
        assert os.path.isfile(os.path.join(ws, "release", "weapons.vpp_pc"))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        srforge_cli.FORGE_ROOT = None


if __name__ == "__main__":
    print("\n== Saints Row Forge test suite ==")
    check("vpp plain round-trip", t_vpp_roundtrip_plain)
    check("vpp condensed+compressed round-trip", t_vpp_roundtrip_condensed_compressed)
    check("str2-style pack", t_vpp_str2_style)
    check("header checksum layout", t_vpp_header_checksum)
    check("garbage vpp rejected", t_vpp_rejects_garbage)
    check("xtbl semantic diff", t_xtbl_diff_semantic)
    check("xtbl duplicate names detected", t_xtbl_duplicate_detection)
    check("xtbl missing record raises", t_xtbl_missing_record_fails)
    check("strings round-trip", t_strings_roundtrip)
    check("asm parse+update (0x0C)", t_asm_parse_0c_and_update)
    check("asm missing container returns None", t_asm_missing_container_is_none)
    check("asm 0x0B parses, size delta sane", t_asm_version_0b_smaller)
    check("patch vpp beats base vpp", t_precedence_patch_wins)
    check("index missing file -> SRF-IDX-001", t_index_missing_file_error)
    check("E2E extract->patch->diff->scope->build", t_e2e_extract_patch_build_diff_receipt)
    check("scope guard rejects collateral damage", t_scope_guard_fails_on_unexpected)
    check("merge union + conflict", t_merge_union_and_conflict)
    check("malformed job rejected cleanly", t_malformed_job_rejected)
    check("CLI honours SRFORGE_GAME_<KEY> per game", t_cli_env_override_per_game)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)
