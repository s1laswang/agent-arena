/** One line of episodes.jsonl, matching canary.types.EpisodeResult. */

export type ToolResult = {
  ok: boolean;
  data: Record<string, unknown>;
  error: string | null;
};

export type Step = {
  t: number;
  day: number;
  tool: string;
  args: Record<string, unknown>;
  result: ToolResult;
};

export type Episode = {
  tier: string;
  seed: number | null;
  agent: string;
  steps: Step[];
  score: number;
  accused: string | null;
  correct: boolean;
  final_day: number;
  end_reason: string;
  meta: Record<string, unknown>;
};

export type LoadedFile = {
  label: string;
  episodes: Episode[];
  index: number;
  warnings: string[];
};
