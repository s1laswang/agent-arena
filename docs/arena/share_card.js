const ZERO_EPSILON = 1e-9;

function resolveDisplayName(entry, fallback = "Player") {
  if (!entry || typeof entry !== "object") {
    return fallback;
  }
  if (typeof entry.name === "string" && entry.name.trim().length > 0) {
    return entry.name.trim();
  }
  if (typeof entry.label === "string" && entry.label.trim().length > 0) {
    return entry.label.trim();
  }
  return fallback;
}

function formatScore(score) {
  if (
    score === null ||
    score === undefined ||
    typeof score === "boolean" ||
    typeof score === "symbol" ||
    typeof score === "object" ||
    (typeof score === "string" && score.trim().length === 0)
  ) {
    throw new TypeError("Score must be a finite number");
  }
  const n = Number(score);
  if (!Number.isFinite(n)) {
    throw new TypeError("Score must be a finite number");
  }
  if (Math.abs(n) <= ZERO_EPSILON) {
    return "0.00";
  }
  if (n > ZERO_EPSILON) {
    return "+" + n.toFixed(2);
  }
  return n.toFixed(2);
}

function formatParticipant(entry) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
    throw new TypeError("Participant entry must be a non-null object");
  }
  const displayName = resolveDisplayName(entry, "Player");
  const day = entry.day ?? entry.final_day ?? null;
  const rawScore = entry.score ?? 0;
  const scoreStr = formatScore(rawScore);
  const scoreNum = Number(rawScore);

  let detail;
  if (
    entry.fooled === true ||
    entry.outcome === "fooled" ||
    entry.status === "fooled" ||
    entry.end_reason === "fooled" ||
    entry.accused_decoy === true
  ) {
    detail = day !== null ? "Fooled Day " + String(day) : "Fooled";
  } else if (
    entry.escaped === true ||
    entry.outcome === "escaped" ||
    entry.status === "escaped"
  ) {
    detail = day !== null ? "Escaped Day " + String(day) : "Escaped";
  } else if (
    entry.caught === true ||
    entry.outcome === "caught" ||
    entry.status === "caught"
  ) {
    detail = day !== null ? "Caught Day " + String(day) : "Caught";
  } else if (
    entry.correct === true ||
    entry.outcome === "win" ||
    entry.outcome === "correct" ||
    entry.status === "win" ||
    entry.status === "correct" ||
    (entry.correct === undefined && scoreNum > ZERO_EPSILON)
  ) {
    detail = day !== null ? "Day " + String(day) : "Correct";
  } else if (
    (entry.correct === false &&
      ((entry.accused !== null &&
        entry.accused !== undefined &&
        entry.accused !== "" &&
        entry.accused !== "NONE") ||
        scoreNum < -ZERO_EPSILON)) ||
    scoreNum < -ZERO_EPSILON ||
    entry.outcome === "wrong" ||
    entry.status === "wrong"
  ) {
    detail = day !== null ? "Wrong Day " + String(day) : "Wrong";
  } else if (
    entry.outcome === "horizon" ||
    entry.status === "horizon" ||
    entry.end_reason === "horizon"
  ) {
    detail = "Horizon";
  } else {
    detail = "No accusation";
  }

  return displayName + " " + scoreStr + " (" + detail + ")";
}

function isMoleEntry(entry) {
  if (!entry || typeof entry !== "object") {
    return false;
  }
  if (
    entry.role === "mole" ||
    entry.isMole === true ||
    entry.escaped === true ||
    entry.outcome === "escaped" ||
    entry.status === "escaped" ||
    entry.caught === true ||
    entry.outcome === "caught" ||
    entry.status === "caught"
  ) {
    return true;
  }
  const lowerName = resolveDisplayName(entry, "").toLowerCase();
  return (
    lowerName === "mole" ||
    lowerName.includes("(mole)") ||
    lowerName.startsWith("mole ") ||
    lowerName.endsWith(" mole")
  );
}

function didParticipantCatchMole(entry) {
  if (!entry || typeof entry !== "object" || isMoleEntry(entry)) {
    return false;
  }
  if (
    entry.fooled === true ||
    entry.outcome === "fooled" ||
    entry.status === "fooled" ||
    entry.end_reason === "fooled" ||
    entry.accused_decoy === true
  ) {
    return false;
  }
  const scoreNum = Number(entry.score ?? 0);
  return (
    entry.correct === true ||
    entry.outcome === "win" ||
    entry.outcome === "correct" ||
    entry.status === "win" ||
    entry.status === "correct" ||
    (entry.correct === undefined && Number.isFinite(scoreNum) && scoreNum > ZERO_EPSILON)
  );
}

function withDefaultSlot(entry, defaultName, extraProps = null) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
    throw new TypeError("Participant slot must be a non-null object");
  }
  const merged = extraProps ? { ...extraProps, ...entry } : { ...entry };
  if (
    (typeof merged.name !== "string" || merged.name.trim().length === 0) &&
    (typeof merged.label !== "string" || merged.label.trim().length === 0)
  ) {
    merged.name = defaultName;
  }
  return merged;
}

function determineFirstCatch(participants) {
  let list = [];
  if (Array.isArray(participants)) {
    list = participants;
  } else if (participants && typeof participants === "object") {
    list = extractParticipants(participants);
  } else {
    return "None";
  }

  const caught = [];
  for (let idx = 0; idx < list.length; idx += 1) {
    const entry = list[idx];
    if (didParticipantCatchMole(entry)) {
      const rawDay = entry.day ?? entry.final_day ?? null;
      const dayVal =
        rawDay !== null && rawDay !== undefined && Number.isFinite(Number(rawDay))
          ? Number(rawDay)
          : Number.POSITIVE_INFINITY;
      const scoreVal = Number.isFinite(Number(entry.score ?? 0))
        ? Number(entry.score ?? 0)
        : Number.NEGATIVE_INFINITY;
      caught.push({
        entry,
        dayVal,
        scoreVal,
        idx,
      });
    }
  }

  if (caught.length === 0) {
    return "None";
  }

  caught.sort((a, b) => {
    if (a.dayVal !== b.dayVal) {
      return a.dayVal - b.dayVal;
    }
    if (b.scoreVal !== a.scoreVal) {
      return b.scoreVal - a.scoreVal;
    }
    return a.idx - b.idx;
  });

  return resolveDisplayName(caught[0].entry, "Player");
}

function isMoleModeResult(result) {
  return (
    result.mode === "mole" ||
    result.mode === 3 ||
    result.mode === "mode3" ||
    (result.mole !== undefined && result.mole !== null && typeof result.mole === "object")
  );
}

function extractParticipants(result) {
  const isMoleMode = isMoleModeResult(result);
  const participants = [];

  if (isMoleMode) {
    if (result.mole && typeof result.mole === "object") {
      participants.push(withDefaultSlot(result.mole, "You (Mole)", { role: "mole" }));
    }
    const opponentArray = Array.isArray(result.opponents)
      ? result.opponents
      : Array.isArray(result.investigators)
        ? result.investigators
        : Array.isArray(result.participants)
          ? result.participants
          : Array.isArray(result.players)
            ? result.players
            : Array.isArray(result.entries)
              ? result.entries
              : null;

    if (opponentArray !== null) {
      for (const item of opponentArray) {
        if (item && typeof item === "object") {
          participants.push({ ...item });
        }
      }
    } else {
      const humanSlot = result.you ?? result.human ?? null;
      if (!result.mole && humanSlot && typeof humanSlot === "object") {
        participants.push(withDefaultSlot(humanSlot, "You (Mole)", { role: "mole" }));
      }
      if (result.gemini && typeof result.gemini === "object") {
        participants.push(withDefaultSlot(result.gemini, "Gemini"));
      }
      if (result.solver && typeof result.solver === "object") {
        participants.push(withDefaultSlot(result.solver, "Solver"));
      }
    }
    return participants;
  }

  const rawArray = Array.isArray(result.participants)
    ? result.participants
    : Array.isArray(result.players)
      ? result.players
      : Array.isArray(result.entries)
        ? result.entries
        : null;

  if (rawArray !== null) {
    for (const item of rawArray) {
      if (item && typeof item === "object") {
        participants.push({ ...item });
      }
    }
    return participants;
  }

  const youSlot = result.you ?? result.human ?? null;
  if (youSlot && typeof youSlot === "object") {
    participants.push(withDefaultSlot(youSlot, "You"));
  }
  if (result.gemini && typeof result.gemini === "object") {
    participants.push(withDefaultSlot(result.gemini, "Gemini"));
  }
  if (result.solver && typeof result.solver === "object") {
    participants.push(withDefaultSlot(result.solver, "Solver"));
  }
  return participants;
}

function normalizeResult(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    throw new TypeError("Share card result must be a non-null object");
  }

  const seed =
    result.seed !== undefined && result.seed !== null && String(result.seed).trim() !== ""
      ? String(result.seed).trim()
      : "0";
  const tier =
    typeof result.tier === "string" && result.tier.trim().length > 0
      ? result.tier.trim()
      : "hard";
  const isMoleMode = isMoleModeResult(result);
  const participants = extractParticipants(result);

  let firstCatch;
  if (typeof result.firstCatch === "string" && result.firstCatch.trim().length > 0) {
    firstCatch = result.firstCatch.trim();
  } else if (typeof result.first_catch === "string" && result.first_catch.trim().length > 0) {
    firstCatch = result.first_catch.trim();
  } else {
    firstCatch = determineFirstCatch(participants);
  }

  return {
    seed,
    tier,
    isMoleMode,
    participants,
    firstCatch,
  };
}

function buildCardFromNorm(norm) {
  const baseHeader = "CANARY ARENA | Seed " + norm.seed + " (" + norm.tier + ")";
  const formattedParticipants = norm.participants.map((p) => formatParticipant(p));
  const joinedParticipants = formattedParticipants.join(" vs ");

  let oneLine;
  if (norm.isMoleMode) {
    oneLine =
      joinedParticipants.length > 0
        ? baseHeader + " | Mole Mode | " + joinedParticipants + " | First catch: " + norm.firstCatch
        : baseHeader + " | Mole Mode | First catch: " + norm.firstCatch;
  } else {
    oneLine =
      joinedParticipants.length > 0
        ? baseHeader + " | " + joinedParticipants + " | First catch: " + norm.firstCatch
        : baseHeader + " | First catch: " + norm.firstCatch;
  }

  const multiHeader = norm.isMoleMode ? baseHeader + " | Mole Mode" : baseHeader;
  const lines = [multiHeader];
  for (const item of formattedParticipants) {
    lines.push("- " + item);
  }
  lines.push("First catch: " + norm.firstCatch);
  const multiLine = lines.join("\n");

  return {
    oneLine,
    multiLine,
    firstCatch: norm.firstCatch,
  };
}

function formatOneLine(result) {
  return buildCardFromNorm(normalizeResult(result)).oneLine;
}

function formatMultiLine(result) {
  return buildCardFromNorm(normalizeResult(result)).multiLine;
}

function formatShareCard(result) {
  return buildCardFromNorm(normalizeResult(result));
}

async function copyShareCard(result, navigatorObj = undefined, options = {}) {
  const card = formatShareCard(result);
  const useMultiLine = Boolean(options && options.multiline);
  const text = useMultiLine ? card.multiLine : card.oneLine;
  const nav =
    navigatorObj !== undefined
      ? navigatorObj
      : typeof navigator !== "undefined"
        ? navigator
        : null;

  if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
    try {
      await nav.clipboard.writeText(text);
      return {
        copied: true,
        text,
        oneLine: card.oneLine,
        multiLine: card.multiLine,
        firstCatch: card.firstCatch,
      };
    } catch (_err) {
      return {
        copied: false,
        text,
        oneLine: card.oneLine,
        multiLine: card.multiLine,
        firstCatch: card.firstCatch,
      };
    }
  }

  return {
    copied: false,
    text,
    oneLine: card.oneLine,
    multiLine: card.multiLine,
    firstCatch: card.firstCatch,
  };
}

const CanaryShareCard = Object.freeze({
  formatScore,
  formatParticipant,
  determineFirstCatch,
  formatOneLine,
  formatMultiLine,
  formatShareCard,
  copyShareCard,
});

if (typeof window !== "undefined" && window !== null) {
  window.CanaryShareCard = CanaryShareCard;
}

export {
  formatScore,
  formatParticipant,
  determineFirstCatch,
  formatOneLine,
  formatMultiLine,
  formatShareCard,
  copyShareCard,
  CanaryShareCard,
};

export default CanaryShareCard;
