from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

from canary.env import Env
from canary.world import DEPTS

ROOT = Path(__file__).resolve().parents[1]
OFFICE_STAGE_JS = ROOT / "docs" / "arena" / "ui" / "office_stage.js"
THIS_TEST_FILE = Path(__file__).resolve()

SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
HASH_TOK = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)


def _find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    candidates = [
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def test_office_stage_file_hygiene_zero_comments_zero_em_dashes() -> None:
    assert OFFICE_STAGE_JS.is_file()
    src = OFFICE_STAGE_JS.read_text(encoding="utf-8")
    assert len(src) > 1000
    assert src.isascii()
    assert SLASH_SLASH not in src
    assert SLASH_STAR not in src
    assert STAR_SLASH not in src
    assert HASH_TOK not in src
    assert EM_DASH not in src
    assert EN_DASH not in src
    assert UNICODE_MINUS not in src
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in src

    test_src = THIS_TEST_FILE.read_text(encoding="utf-8")
    assert test_src.isascii()
    assert SLASH_SLASH not in test_src
    assert SLASH_STAR not in test_src
    assert STAR_SLASH not in test_src
    assert HASH_TOK not in test_src
    assert EM_DASH not in test_src
    assert EN_DASH not in test_src
    assert UNICODE_MINUS not in test_src
    tokens = list(tokenize.generate_tokens(io.StringIO(test_src).readline))
    assert [tok for tok in tokens if tok.type == tokenize.COMMENT] == []


def test_office_stage_exports_and_zero_external_dependencies() -> None:
    src = OFFICE_STAGE_JS.read_text(encoding="utf-8")
    assert not re.search(r"^\s*import\s+", src, flags=re.MULTILINE)

    required_exports = [
        "OFFICE_ZONES",
        "buildOfficeMap",
        "OfficeStage",
        "loadSpritePack",
        "getCreditsText",
        "setClock",
        "applyObservableEvent",
        "revealOutcome",
        "setHumanMole",
    ]
    for sym in required_exports:
        pattern = rf"\bexport\s+(?:async\s+)?(?:const|function|class)\s+{re.escape(sym)}\b"
        assert re.search(pattern, src), f"missing export {sym}"

    for method in (
        "loadSpritePack",
        "getCreditsText",
        "setClock",
        "applyObservableEvent",
        "revealOutcome",
        "setHumanMole",
        "step",
        "render",
        "start",
        "destroy",
    ):
        assert re.search(rf"\b{re.escape(method)}\s*\(", src), f"missing method {method}"


def test_office_stage_zones_grid_and_static_hidden_truth_guards() -> None:
    src = OFFICE_STAGE_JS.read_text(encoding="utf-8")
    assert "TILE_SIZE = 16" in src
    assert "GRID_COLS = 40" in src
    assert "GRID_ROWS = 24" in src

    assert len(DEPTS) == 5
    for dept in DEPTS:
        assert f'"{dept}"' in src

    for facility in (
        "Meeting Room A",
        "Meeting Room B",
        "Coffee Corner",
        "Server Room",
        "Security Desk",
    ):
        assert f'"{facility}"' in src

    for phase in ("morning", "afternoon", "dusk", "night"):
        assert f'"{phase}"' in src

    for evt_kind in (
        "list_employees",
        "plant_canary",
        "check_leak_feed",
        "interview",
        "restrict_access",
        "unrestrict_access",
        "read_access_logs",
        "social_rumour",
        "social_grudge",
        "advance_day",
    ):
        assert f'"{evt_kind}"' in src

    for forbidden in ("mole", "_world", "secret"):
        assert f'"{forbidden}"' in src
    assert 'episodeDone === true || mode === "mole"' in src
    assert "if (!this.episodeDone)" in src
    assert 'if (this.mode !== "mole")' in src


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_office_stage_runtime_40_employees_events_and_sprite_adapter() -> None:
    node_bin = _find_node()
    assert node_bin is not None

    hard_env = Env("hard", 0)
    easy_env = Env("easy", 0)
    med_env = Env("medium", 0)
    hard_staff = hard_env.call("list_employees", {}).data["employees"]
    easy_staff = easy_env.call("list_employees", {}).data["employees"]
    med_staff = med_env.call("list_employees", {}).data["employees"]
    assert len(hard_staff) == 40
    assert len(easy_staff) == 12
    assert len(med_staff) == 20

    script = f"""
    import * as M from {json.dumps(OFFICE_STAGE_JS.as_uri())};

    const requiredZones = [
      "Engineering",
      "Finance",
      "Legal",
      "Research",
      "Sales",
      "Meeting Room A",
      "Meeting Room B",
      "Coffee Corner",
      "Server Room",
      "Security Desk"
    ];
    for (const z of requiredZones) {{
      if (!M.OFFICE_ZONES[z]) {{
        throw new Error("Missing zone: " + z);
      }}
    }}

    for (const staff of [{json.dumps(easy_staff)}, {json.dumps(med_staff)}, {json.dumps(hard_staff)}]) {{
      const map = M.buildOfficeMap(staff);
      if (map.width !== 40 || map.height !== 24 || map.tileSize !== 16) {{
        throw new Error("Unexpected grid dimensions");
      }}
      if (map.desks.length < 40) {{
        throw new Error("Expected at least 40 desks, got " + map.desks.length);
      }}
      const assignedIds = Object.keys(map.deskByEmployee);
      if (assignedIds.length !== staff.length) {{
        throw new Error("Expected all employees assigned");
      }}
      const uniqueCoords = new Set(
        assignedIds.map((id) => map.deskByEmployee[id].x + ":" + map.deskByEmployee[id].y)
      );
      if (uniqueCoords.size !== staff.length) {{
        throw new Error("Duplicate desk coordinates detected");
      }}
      for (const id of assignedIds) {{
        const d = map.deskByEmployee[id];
        const path = M.findWalkPath(
          map,
          {{ x: d.chairX, y: d.chairY }},
          map.waypoints["Coffee Corner"][0]
        );
        for (let i = 1; i < path.length; i += 1) {{
          const stepDist =
            Math.abs(path[i].x - path[i - 1].x) + Math.abs(path[i].y - path[i - 1].y);
          if (stepDist !== 1 || !map.walkable[path[i].y][path[i].x]) {{
            throw new Error("Non-walkable path for " + id);
          }}
        }}
      }}
    }}

    const drawCalls = [];
    const mockCanvas = {{
      width: 640,
      height: 384,
      style: {{}},
      getContext() {{
        return {{
          imageSmoothingEnabled: true,
          save() {{ drawCalls.push("save"); }},
          restore() {{ drawCalls.push("restore"); }},
          clearRect() {{ drawCalls.push("clearRect"); }},
          fillRect() {{ drawCalls.push("fillRect"); }},
          strokeRect() {{ drawCalls.push("strokeRect"); }},
          fillText(t) {{ drawCalls.push("text:" + t); }},
          drawImage() {{ drawCalls.push("drawImage"); }}
        }};
      }}
    }};

    const stage = new M.OfficeStage(mockCanvas);
    M.applyObservableEvent(stage, {{
      tool: "list_employees",
      data: {{ employees: {json.dumps(hard_staff)} }}
    }});

    if (M.setClock(stage, {{ day: 1, nDays: 21, actionsUsed: 0, perDay: 8, V: 1.0 }}).phase !== "morning") {{
      throw new Error("Expected morning");
    }}
    if (stage.setClock({{ actionsUsed: 3, perDay: 8 }}).phase !== "afternoon") {{
      throw new Error("Expected afternoon");
    }}
    if (stage.setClock({{ actionsUsed: 6, perDay: 8 }}).phase !== "dusk") {{
      throw new Error("Expected dusk");
    }}
    if (stage.setClock({{ actionsUsed: 8, perDay: 8 }}).phase !== "night") {{
      throw new Error("Expected night");
    }}

    stage.applyObservableEvent({{
      type: "plant_canary",
      canary_id: "c1",
      doc_title: "Q1 roadmap",
      assignment: {{ e00: "A", e01: "B", e02: "C" }}
    }});
    if (stage.deskCanaries.get("e01").variant !== "B") {{
      throw new Error("Expected canary variant B on e01 desk");
    }}

    stage.applyObservableEvent({{
      type: "check_leak_feed",
      items: [{{ doc_id: "c1", variant: "B", surfaced_day: 2 }}]
    }});
    if (!stage.leakBanner.active || !stage.highlightedVariantDesks.has("e01")) {{
      throw new Error("Expected leak banner and highlighted variant desk");
    }}

    stage.applyObservableEvent({{
      type: "interview",
      employee: "e05",
      topic: "contacts_outside"
    }});
    if (!stage.activeInterview || stage.activeInterview.room !== "Security Desk") {{
      throw new Error("Expected Security Desk interview");
    }}

    stage.applyObservableEvent({{ type: "restrict_access", employee: "e07" }});
    if (!stage.restrictedIds.has("e07")) {{
      throw new Error("Expected e07 restricted");
    }}
    stage.applyObservableEvent({{ type: "unrestrict_access", employee: "e07" }});
    if (stage.restrictedIds.has("e07")) {{
      throw new Error("Expected e07 unrestricted");
    }}

    stage.applyObservableEvent({{
      type: "read_access_logs",
      day_from: 1,
      day_to: 2,
      logs: [
        {{ day: 1, employee: "e09", doc_id: "d1-1", after_hours: true }},
        {{ day: 1, employee: "e10", doc_id: "d1-1", after_hours: false }}
      ]
    }});
    if (!stage.afterHoursMarks.has("e09") || stage.afterHoursMarks.has("e10")) {{
      throw new Error("Expected only e09 marked after_hours");
    }}

    stage.applyObservableEvent({{
      type: "social_rumour",
      from: "e11",
      to: "e12"
    }});
    stage.applyObservableEvent({{
      type: "social_grudge",
      from: "e13",
      to: "e14"
    }});
    if (stage.socialInteractions.length !== 2) {{
      throw new Error("Expected 2 social interactions");
    }}

    stage.applyObservableEvent({{
      type: "advance_day",
      data: {{ day: 2, V: 0.95 }}
    }});
    if (stage.overnightPulse <= 0 || stage.clock.day !== 2) {{
      throw new Error("Expected overnight pulse on advance_day");
    }}

    stage.start();
    stage.step(120);
    const snap = stage.render();
    stage.destroy();
    if (snap.employeeCount !== 40 || snap.zoneCount !== 10 || drawCalls.length === 0) {{
      throw new Error("Unexpected render snapshot");
    }}

    const pack = await M.loadSpritePack(stage, {{
      baseUrl: "docs/arena/assets",
      tileSheet: "tiles.png",
      charSheet: "chars.png",
      frameW: 16,
      frameH: 16,
      creditsText: "Kenney CC0",
      sprites: {{ desk: {{ x: 0, y: 0, w: 16, h: 16 }} }}
    }});
    if (!pack.loaded || M.getCreditsText(stage) !== "Kenney CC0") {{
      throw new Error("Sprite pack credits mismatch");
    }}
    console.log("RUNTIME_OK");
    """
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "RUNTIME_OK" in proc.stdout


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_office_stage_hidden_truth_guard_rejects_leaks_until_done_or_mole_mode() -> None:
    node_bin = _find_node()
    assert node_bin is not None

    script = f"""
    import * as M from {json.dumps(OFFICE_STAGE_JS.as_uri())};

    function mustThrow(fn, label) {{
      let threw = false;
      try {{
        fn();
      }} catch (err) {{
        threw = true;
      }}
      if (!threw) {{
        throw new Error("Expected error for: " + label);
      }}
    }}

    mustThrow(() => new M.OfficeStage(null, {{ mole: "e03" }}), "init mole");
    mustThrow(() => new M.OfficeStage(null, {{ _world: {{ mole: "e03" }} }}), "init _world");
    mustThrow(() => new M.OfficeStage(null, {{ secret: "topsecret" }}), "init secret");

    const stage = new M.OfficeStage();
    stage.applyObservableEvent({{
      type: "list_employees",
      employees: [
        {{ id: "e00", name: "Aino Virtanen", dept: "Engineering", role: "engineer" }},
        {{ id: "e01", name: "Mikko Korhonen", dept: "Finance", role: "analyst" }}
      ]
    }});

    mustThrow(
      () => stage.applyObservableEvent({{ type: "status", mole: "e01" }}),
      "event mole"
    );
    mustThrow(
      () => stage.applyObservableEvent({{ type: "status", data: {{ _world: {{}} }} }}),
      "event nested _world"
    );
    mustThrow(
      () => stage.applyObservableEvent({{ type: "status", args: {{ secret: "k" }} }}),
      "event nested secret"
    );
    mustThrow(
      () => M.revealOutcome(stage, {{ moleId: "e01", accusedId: "e01", correct: true }}),
      "revealOutcome before episodeDone"
    );
    mustThrow(
      () => M.setHumanMole(stage, {{ employeeId: "e01", leakedDocIds: ["d1-1"] }}),
      "setHumanMole outside mole mode"
    );

    stage.applyObservableEvent({{
      type: "accuse",
      employee: "e01",
      data: {{ accused: "e01", episode_over: true }}
    }});
    const outcome = M.revealOutcome(stage, {{
      moleId: "e01",
      accusedId: "e01",
      correct: true
    }});
    if (outcome.moleId !== "e01" || !outcome.correct) {{
      throw new Error("Expected revealOutcome after episodeDone");
    }}
    stage.render();

    const moleStage = new M.OfficeStage(null, {{
      mode: "mole",
      mole: "e00",
      staff: [{{ id: "e00", name: "Aino Virtanen", dept: "Engineering", role: "engineer" }}]
    }});
    const hm = M.setHumanMole(moleStage, {{
      employeeId: "e00",
      leakedDocIds: ["d1-1"]
    }});
    if (hm.employeeId !== "e00" || hm.leakedDocIds.length !== 1) {{
      throw new Error("Expected setHumanMole in mole mode");
    }}
    moleStage.render();
    console.log("GUARD_OK");
    """
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "GUARD_OK" in proc.stdout
