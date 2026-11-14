// Browser-side half of the parity test: replay a recorded action list in Pyodide using the BUILT site files.
// usage: node game/tests/parity.mjs <pyodide_dir> <site_py_dir> <actions.json>
// prints the Env verdict as JSON. tests/test_game.py compares it with the CPython replay.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [pyodideDir, sitePy, actionsFile] = process.argv.slice(2);
const { loadPyodide } = await import(pathToFileURL(path.join(pyodideDir, "pyodide.mjs")).href);
const py = await loadPyodide({ indexURL: pyodideDir.endsWith("/") ? pyodideDir : pyodideDir + "/" });

const manifest = JSON.parse(fs.readFileSync(path.join(sitePy, "manifest.json"), "utf8"));
for (const rel of manifest.files) {
  const dst = "/home/pyodide/" + rel;
  py.FS.mkdirTree(dst.substring(0, dst.lastIndexOf("/")));
  py.FS.writeFile(dst, fs.readFileSync(path.join(sitePy, rel)));
}
py.globals.set("ACTIONS_JSON", fs.readFileSync(actionsFile, "utf8"));
const out = py.runPython(`
import json, sys
sys.path.insert(0, "/home/pyodide")
import canary_game
rec = json.loads(ACTIONS_JSON)
json.dumps(canary_game.replay(rec["seed"], rec["actions"]), sort_keys=True)
`);
console.log(out);
