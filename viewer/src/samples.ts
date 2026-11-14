export type SampleId = "solver" | "heuristic" | "restrict";

export const SAMPLES: { id: SampleId; file: string; label: string; hint: string }[] = [
  { id: "solver", file: "solver-medium.jsonl", label: "Solver", hint: "medium · seeds 0–2" },
  { id: "heuristic", file: "heuristic-medium.jsonl", label: "Heuristic", hint: "medium · seeds 0–2" },
  { id: "restrict", file: "restrict-all-medium.jsonl", label: "Restrict-all", hint: "medium · seed 0" },
];

export async function fetchSample(id: SampleId): Promise<{ label: string; text: string }> {
  const spec = SAMPLES.find((s) => s.id === id);
  if (!spec) throw new Error(`Unknown sample ${id}`);
  const url = `${import.meta.env.BASE_URL}samples/${spec.file}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new Error(
      `Could not load ${spec.file}. Serve the built viewer with npm run preview — opening the HTML file directly cannot fetch samples.`,
    );
  }
  if (!res.ok) {
    throw new Error(`Could not load ${spec.file} (${res.status}). Use npm run dev or npm run preview.`);
  }
  return { label: spec.file, text: await res.text() };
}
