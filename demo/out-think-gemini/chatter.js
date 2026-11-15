(function (root) {
  "use strict";

  var SCOPE_LABEL = "demo/research layer (v1.5 candidate), not part of the judged v1.4 environment";

  var SUPPORTED_ENCODINGS = [
    "plaintext",
    "base64",
    "base64url",
    "base32",
    "base32hex",
    "base85",
    "ascii85",
    "hex",
    "hex_delimited",
    "url_encoding",
    "double_url_encoding",
    "html_entities",
    "unicode_escape",
    "quoted_printable",
    "zlib_base64",
    "rot13",
    "caesar_shift",
    "atbash",
    "rot47",
    "reversed",
    "reversed_words",
    "zero_width_strip",
    "zero_width_stego",
    "unicode_tags",
    "homoglyph",
    "diacritics_strip",
    "leetspeak",
    "spaced_chars",
    "acrostic_lines",
    "acrostic_sentences",
    "acrostic_words",
    "nth_char_stride",
    "binary_ascii",
    "octal_ascii",
    "decimal_ascii",
    "morse_code",
    "split_across_messages"
  ];

  var TRUTH_INPUT_KEYS = {
    mole: true,
    mole_id: true,
    moleId: true,
    true_mole: true,
    trueMole: true,
    is_mole: true,
    isMole: true,
    decoy: true,
    is_decoy: true,
    isDecoy: true,
    mole_strategy: true,
    moleStrategy: true,
    ledger: true,
    truth: true,
    secret: true,
    rng_state: true,
    rngState: true,
    ground_truth_mole: true,
    groundTruthMole: true
  };

  var PROVENANCE_STATS = {
    environment_scope: SCOPE_LABEL,
    role: "world_text",
    model_id: "gemini-4-carbon",
    tiers_version: "v1.4",
    verified_folders: 16,
    verified_carbon_folders: 16,
    calls: 1637,
    api_calls: 1637,
    input_tokens: 54755491,
    output_tokens: 791997,
    thinking_tokens: 791365,
    cached_tokens: 50867472,
    cost_usd: 22.728348,
    personas: 648,
    unique_personas: 648,
    worlds: 24,
    unique_worlds: 24,
    worlds_by_tier: {
      easy: 4,
      medium: 10,
      hard: 10
    },
    personas_by_tier: {
      easy: 48,
      medium: 200,
      hard: 400
    },
    live_interviews: 120,
    interview_worlds: 15,
    interview_batches: 3,
    signal_calibration_accuracy: 1.0,
    signal_calibration_pct: 100.0,
    signal_calibration_ci95: [0.969, 1.0],
    counterfactual_checks: 360,
    counterfactual_invariance_rate: 1.0,
    counterfactual_invariance_ci95: [0.9894, 1.0],
    biased_chatter_messages: 70,
    live_llm_biased_messages: 70,
    ablation_episodes: 36,
    paired_ablation_seeds: 6,
    solver_rumor_distraction_rate: 0.0,
    carbon_rumor_distraction_rate: 0.6667,
    carbon_false_rumor_accusation_rate: 0.0,
    dynamic_events: 33,
    dynamic_event_worlds: 11,
    thinking_calibrated_worlds: 6,
    encodings_scanned: 37,
    supported_encodings_count: 37,
    leaks_detected: 0,
    truth_leak_violations: 0,
    prompt_truth_leak_violations: 0,
    lint_violations: 0,
    stego_encoding_violations: 0,
    fallback_count: 0,
    all_clean: true,
    summary_line:
      "Role 1 world_text (gemini-4-carbon): 16 verified carbon folders, 1,637 API calls ($22.73), 648 personas across 24 worlds, 120 live interviews with 100% signal calibration, and 0 leaks across 37 encodings."
  };

  var CANARY_VS_RUMOR_EXPLAINER = {
    headline: "Why Canary Partitions Beat Office Rumors",
    core_principle:
      "Workplace rumors reflect schedule stereotypes, social friction, and availability bias (zero bits of partition evidence), whereas a planted canary assigns distinct fingerprinted variants across recipient subsets so each observed external quote narrows the exact holder set.",
    ablation_evidence:
      "Across 36 paired Role 1 ablation episodes (70 live gemini-4-carbon biased chatter messages), office rumors pulled LLM investigation actions onto innocent targets on 66.7% of seeds while the Bayesian canary solver stayed at 0.0% distraction.",
    decision_rule:
      "Treat Slack and hallway gossip as non-diagnostic atmosphere; update posteriors only from canary variant exposure sets and verified access logs, and hold fire until top posterior clears the break-even threshold."
  };

  var TIER_CONTEXT = {
    easy: {
      cadence: "routine twelve-person sprint handoff",
      pressure: "compact team visibility with clear document ownership",
      artifact_group: "seed briefing packet"
    },
    medium: {
      cadence: "cross-functional twenty-person milestone review",
      pressure: "overlapping review threads across partner and assay teams",
      artifact_group: "phase readout annex"
    },
    hard: {
      cadence: "high-density forty-person multi-division release",
      pressure: "simultaneous board, clinical, and infrastructure deadlines",
      artifact_group: "unredacted strategy dossier"
    }
  };

  var SLACK_HALLWAY_POOL = [
    {
      kind: "slack",
      channel: "slack:release-sync",
      speaker_role: "Release Coordinator",
      topic: "freeze checklist",
      text: "Reminder that slide exports for the partner review lock at 18:00; post checksums in the release thread before signing off."
    },
    {
      kind: "hallway",
      channel: "hallway:coffee-station",
      speaker_role: "Assay Technician",
      topic: "calibration queue",
      text: "Two plate readers ran warm overnight, so morning validation tables are running twenty minutes behind the usual standup slot."
    },
    {
      kind: "slack",
      channel: "slack:ops-handoff",
      speaker_role: "Platform SRE",
      topic: "audit log rotation",
      text: "Document gateway logs finished archiving cleanly; read and export timestamps are synced to UTC across all workspaces."
    },
    {
      kind: "slack",
      channel: "slack:data-governance",
      speaker_role: "Compliance Analyst",
      topic: "watermark policy",
      text: "Controlled briefing drafts now carry per-group distribution tags so reviewers can trace which copy left the workspace."
    },
    {
      kind: "hallway",
      channel: "hallway:elevator-lobby",
      speaker_role: "Alliances Lead",
      topic: "steering agenda",
      text: "External counsel asked for another pass on the diligence timeline, so half the strategy floor brought thermoses for a long evening."
    },
    {
      kind: "slack",
      channel: "slack:lab-logistics",
      speaker_role: "Sample Archivist",
      topic: "cold-room inventory",
      text: "Barcodes on batch seven matched the manifest on first scan; closing the afternoon chain-of-custody ticket now."
    },
    {
      kind: "hallway",
      channel: "hallway:print-alcove",
      speaker_role: "Program Manager",
      topic: "deck pagination",
      text: "Please stop printing draft appendices from local desktops; use the shared review folder so page numbers stay aligned."
    },
    {
      kind: "slack",
      channel: "slack:biostats-qc",
      speaker_role: "Biostatistician",
      topic: "confidence intervals",
      text: "Re-ran the sensitivity script against locked tables and confirmed zero drift from yesterday's snapshot."
    },
    {
      kind: "slack",
      channel: "slack:sec-ops",
      speaker_role: "Security Duty Officer",
      topic: "badge reader maintenance",
      text: "East wing turnstile firmware updated at noon; all evening badge swipes reconcile one-to-one with workstation logins."
    },
    {
      kind: "hallway",
      channel: "hallway:north-corridor",
      speaker_role: "Finance Controller",
      topic: "vendor forecast",
      text: "Quarter-close accruals are due before Friday noon, which explains why three teams booked quiet rooms back to back."
    },
    {
      kind: "slack",
      channel: "slack:clinical-ops",
      speaker_role: "Clinical Trial Coordinator",
      topic: "site query batch",
      text: "Regional monitors cleared fourteen routine data queries; updated summary sheets stay inside the restricted vault."
    },
    {
      kind: "hallway",
      channel: "hallway:atrium-bench",
      speaker_role: "Systems Architect",
      topic: "staging cutover",
      text: "We mirrored permissions on the staging repository so nobody needs elevated tokens just to verify formatting."
    },
    {
      kind: "slack",
      channel: "slack:exec-briefings",
      speaker_role: "Chief of Staff Office",
      topic: "briefing distribution",
      text: "Distribution lists for tomorrow's readout memo are frozen; request explicit approval before forwarding any annex."
    },
    {
      kind: "hallway",
      channel: "hallway:kitchenette",
      speaker_role: "QA Reviewer",
      topic: "sign-off backlog",
      text: "Everyone blames slow tooling during crunch week, yet ninety percent of delays come from last-minute wording edits."
    },
    {
      kind: "slack",
      channel: "slack:infra-alerts",
      speaker_role: "Storage Engineer",
      topic: "snapshot retention",
      text: "Hourly immutable snapshots remain active on all confidential folders; nothing can be overwritten without leaving an audit row."
    },
    {
      kind: "hallway",
      channel: "hallway:west-stairwell",
      speaker_role: "Regulatory Writer",
      topic: "submission formatting",
      text: "Cross-referencing citations took longer than expected, though the final glossary finally passed automated checks."
    }
  ];

  var BIAS_RUMOR_POOL = [
    {
      bias_type: "schedule_stereotyping",
      channel: "hallway:watercooler",
      speaker_role: "Breakroom Speculation",
      topic: "late-shift suspicion",
      text: "People keep whispering that whoever badges in after 21:00 must be copying sensitive files when the floor is empty.",
      why_canary_beats_rumor:
        "After-hours work is noisy base-rate behavior during deadline weeks; a canary partition tests who actually held the exact fingerprinted variant that surfaced externally."
    },
    {
      bias_type: "availability_bias",
      channel: "slack:backchannel-vent",
      speaker_role: "Backchannel Rumor",
      topic: "standup tension",
      text: "Did you hear how sharply that reviewer pushed back on executive timeline cuts this morning? Folks say frustration like that explains the press tip.",
      why_canary_beats_rumor:
        "Vocal disagreement in meetings has zero mathematical link to external disclosure; orthogonal canary splits isolate document holders without penalizing candid debate."
    },
    {
      bias_type: "outgroup_attribution",
      channel: "hallway:breakroom",
      speaker_role: "Hallway Gossip",
      topic: "recent transfer chatter",
      text: "Office talk keeps circling around the newest cross-department transfer simply because they asked how archive permissions are structured.",
      why_canary_beats_rumor:
        "New-transfer suspicion is classic outgroup bias; Bayesian posterior updates weight variant recipient membership equally regardless of tenure."
    },
    {
      bias_type: "tone_policing_bias",
      channel: "slack:side-thread",
      speaker_role: "Side-Channel Speculation",
      topic: "terse replies",
      text: "Someone answered audit scheduling questions in one-line messages all week, and half the floor treats short replies like a guilty conscience.",
      why_canary_beats_rumor:
        "Terse communication style is a fixed persona trait; Role 1 interviews calibrate 100% to environment signals while canary variants provide hard set-elimination."
    },
    {
      bias_type: "recency_gossip",
      channel: "hallway:copy-room",
      speaker_role: "Copy-Room Rumor",
      topic: "last viewer fallacy",
      text: "Rumor in the copy room says the last person to open a shared folder before lunch has to be responsible whenever trade press quotes a memo.",
      why_canary_beats_rumor:
        "Timestamp recency ignores earlier exports from prior days; planted canary variants tag content lineage across days so early copies remain attributable."
    },
    {
      bias_type: "halo_horn_effect",
      channel: "slack:watercooler-dm",
      speaker_role: "Informal Gossip",
      topic: "missed-deadline blame",
      text: "Because one sub-team slipped their milestone last quarter, hallway chatter assumes poor discipline there caused the confidential leak too.",
      why_canary_beats_rumor:
        "Past schedule slips do not partition document access; only disjoint or binary-split canary variants shrink the candidate set with provable precision."
    },
    {
      bias_type: "privacy_habit_bias",
      channel: "hallway:lounge",
      speaker_role: "Lounge Speculation",
      topic: "closed-door assumption",
      text: "Whenever a lead books a solo phone booth twice in one afternoon, corridor gossip immediately spins stories about outside contacts.",
      why_canary_beats_rumor:
        "Focused solo work looks identical to secrecy from the hallway; fingerprinted canary documents separate legitimate readers from the source of an external quote."
    },
    {
      bias_type: "role_scapegoating",
      channel: "slack:unverified-chat",
      speaker_role: "Office Rumor Mill",
      topic: "external-facing blame",
      text: "People automatically point fingers at external-facing coordinators first, forgetting that internal technical leads hold the exact same read clearance.",
      why_canary_beats_rumor:
        "Job-title stereotypes over-accuse alliance and operations staff (-1.00 false accusation risk); canary partitions cut across departments to pin the true holder."
    }
  ];

  var DEMEANORS = [
    "measured",
    "methodical",
    "terse",
    "candid",
    "matter-of-fact",
    "composed"
  ];

  var INTERVIEW_OPENERS = [
    "My work queue stayed tied to documented team deliverables",
    "Every file I opened matched our scheduled review checklist",
    "I kept my activity strictly inside approved workspace folders",
    "All edits from my workstation followed standard change control",
    "My access history reflects routine preparation for our milestone gate",
    "I only pulled materials assigned to my functional review lane",
    "Each document read on my account maps to an open tracking ticket",
    "I handled draft sections through the audited repository workflow"
  ];

  var INTERVIEW_WORKFLOWS = [
    "reconciling annex tables and cross-checking version checksums",
    "verifying summary figures against locked upstream snapshots",
    "updating section redlines ahead of the cross-team sign-off window",
    "auditing dependency notes so downstream reviewers had clean inputs",
    "aligning milestone risk matrices with the latest operational metrics",
    "validating configuration manifests before the scheduled freeze",
    "packaging approved briefing charts for internal governance review",
    "resolving open reviewer comments on the shared specification draft"
  ];

  var INTERVIEW_VERIFICATIONS = [
    "You can match every read event against gateway timestamps and version history.",
    "No unwatermarked copies or personal exports ever left my session.",
    "Check the repository commit log and distribution tags to confirm my scope.",
    "Every export stayed inside the restricted review vault with full audit trails.",
    "My badge swipes, ticket comments, and file reads line up minute for minute.",
    "Compare the variant distribution list before drawing conclusions from hallway talk.",
    "All handoffs went to named internal reviewers on the frozen roster.",
    "Gateway telemetry will show zero external transfers from my credentials."
  ];

  var COUNT_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty"
  ];

  function isObject(val) {
    return val !== null && typeof val === "object" && !Array.isArray(val);
  }

  function stripTruthFields(raw) {
    if (!isObject(raw)) {
      return {};
    }
    var clean = {};
    var keys = Object.keys(raw);
    for (var i = 0; i < keys.length; i += 1) {
      var k = keys[i];
      if (!Object.prototype.hasOwnProperty.call(TRUTH_INPUT_KEYS, k)) {
        clean[k] = raw[k];
      }
    }
    return clean;
  }

  function firstDefined(obj, keys) {
    if (!isObject(obj)) {
      return undefined;
    }
    for (var i = 0; i < keys.length; i += 1) {
      var k = keys[i];
      if (obj[k] !== undefined && obj[k] !== null) {
        return obj[k];
      }
    }
    return undefined;
  }

  function looksLikeEmpCode(tok) {
    if (!tok || tok.length !== 3) {
      return false;
    }
    var c0 = tok.charCodeAt(0);
    var c1 = tok.charCodeAt(1);
    var c2 = tok.charCodeAt(2);
    var isLetter = (c0 >= 65 && c0 <= 90) || (c0 >= 97 && c0 <= 122);
    var isDig1 = c1 >= 48 && c1 <= 57;
    var isDig2 = c2 >= 48 && c2 <= 57;
    return isLetter && isDig1 && isDig2;
  }

  function sanitizeLabel(val, fallback) {
    if (val === undefined || val === null) {
      return fallback;
    }
    var raw = String(val);
    var chars = [];
    for (var i = 0; i < raw.length; i += 1) {
      var code = raw.charCodeAt(i);
      if (code === 0x2012 || code === 0x2013 || code === 0x2014 || code === 0x2015) {
        chars.push("-");
      } else if (code === 35 || code === 42 || code === 47 || code === 60 || code === 62) {
        chars.push(" ");
      } else if (code >= 32 && code <= 126) {
        chars.push(raw.charAt(i));
      }
    }
    var joined = chars.join("").trim();
    if (!joined) {
      return fallback;
    }
    var parts = joined.split(/\s+/);
    var safeParts = [];
    for (var p = 0; p < parts.length; p += 1) {
      var w = parts[p];
      var low = w.toLowerCase();
      if (
        looksLikeEmpCode(w) ||
        low.indexOf("mole") !== -1 ||
        low.indexOf("leaker") !== -1 ||
        low.indexOf("culprit") !== -1 ||
        low.indexOf("traitor") !== -1 ||
        low.indexOf("spy") !== -1 ||
        low.indexOf("informant") !== -1
      ) {
        continue;
      }
      safeParts.push(w);
    }
    var finalStr = safeParts.join(" ").trim();
    return finalStr.length > 0 ? finalStr : fallback;
  }

  function normalizeTier(rawTier) {
    var s = sanitizeLabel(rawTier, "hard").toLowerCase();
    if (s === "easy" || s === "medium" || s === "hard") {
      return s;
    }
    return "hard";
  }

  function normalizeInt(val, fallback, minVal) {
    if (val === undefined || val === null || val === "") {
      return fallback;
    }
    var n = Number(val);
    if (!Number.isFinite(n)) {
      return fallback;
    }
    var floored = n >= 0 ? Math.floor(n) : Math.ceil(n);
    if (minVal !== undefined && floored < minVal) {
      return minVal;
    }
    return floored;
  }

  function normalizeSuspectId(rawId) {
    if (rawId === undefined || rawId === null) {
      return "e01";
    }
    var s = String(rawId).trim();
    return s.length > 0 ? s : "e01";
  }

  function fnv1a32(str) {
    var h = 0x811c9dc5;
    var input = String(str);
    for (var i = 0; i < input.length; i += 1) {
      h ^= input.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  }

  function createRng(seedUint32) {
    var state = (seedUint32 >>> 0) || 0x6d2b79f5;
    return function nextUint32() {
      state = (state + 0x6d2b79f5) >>> 0;
      var t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return (t ^ (t >>> 14)) >>> 0;
    };
  }

  function pickDistinctIndices(poolLen, count, rng) {
    var indices = [];
    for (var i = 0; i < poolLen; i += 1) {
      indices.push(i);
    }
    var limit = Math.min(poolLen, Math.max(1, count));
    for (var j = 0; j < limit; j += 1) {
      var span = poolLen - j;
      var swapIdx = j + (rng() % span);
      var tmp = indices[j];
      indices[j] = indices[swapIdx];
      indices[swapIdx] = tmp;
    }
    return indices.slice(0, limit);
  }

  function formatAfterHoursPhrase(afterHoursCount) {
    if (afterHoursCount <= 0) {
      return "zero after-hours badge sessions on my log, since all my work happened during core daytime hours";
    }
    if (afterHoursCount === 1) {
      return "one after-hours check-in on my log to finish a scheduled handoff before the morning standup";
    }
    var word = afterHoursCount <= 20 ? COUNT_WORDS[afterHoursCount] : "multiple";
    return (
      word +
      " after-hours sessions on my log, each tied to pre-scheduled deadline windows across time zones"
    );
  }

  function getSuspectInterview(rawOpts) {
    var clean = stripTruthFields(rawOpts);
    var tier = normalizeTier(firstDefined(clean, ["tier", "difficulty"]));
    var seed = normalizeInt(firstDefined(clean, ["seed", "world_seed", "worldSeed"]), 0);
    var suspectId = normalizeSuspectId(
      firstDefined(clean, ["suspectId", "suspect_id", "employeeId", "employee_id", "employee", "id"])
    );
    var dept = sanitizeLabel(
      firstDefined(clean, ["dept", "department", "team", "division"]),
      "Operations"
    );
    var role = sanitizeLabel(
      firstDefined(clean, ["role", "job_title", "jobTitle", "title", "position"]),
      "Staff Specialist"
    );
    var afterHoursCount = normalizeInt(
      firstDefined(clean, ["afterHoursCount", "after_hours_count", "afterHours", "after_hours"]),
      0,
      0
    );

    var canonicalKey =
      tier +
      ":" +
      String(seed) +
      ":" +
      suspectId +
      ":" +
      dept +
      ":" +
      role +
      ":" +
      String(afterHoursCount);

    var rng = createRng(fnv1a32("outthink-interview|" + canonicalKey));
    var demeanor = DEMEANORS[rng() % DEMEANORS.length];
    var opener = INTERVIEW_OPENERS[rng() % INTERVIEW_OPENERS.length];
    var workflow = INTERVIEW_WORKFLOWS[rng() % INTERVIEW_WORKFLOWS.length];
    var verification = INTERVIEW_VERIFICATIONS[rng() % INTERVIEW_VERIFICATIONS.length];
    var tierCtx = TIER_CONTEXT[tier] || TIER_CONTEXT.hard;
    var schedulePhrase = formatAfterHoursPhrase(afterHoursCount);

    var question =
      afterHoursCount > 0
        ? "Walk through your " +
          dept +
          " (" +
          role +
          ") file access and explain the evening activity recorded during this " +
          tierCtx.cadence +
          "."
        : "Walk through your " +
          dept +
          " (" +
          role +
          ") document handling during this " +
          tierCtx.cadence +
          ".";

    var responseText =
      opener +
      " in " +
      dept +
      " as " +
      role +
      ", specifically " +
      workflow +
      " for the " +
      tierCtx.artifact_group +
      ". There are " +
      schedulePhrase +
      ". " +
      verification;

    return {
      key: canonicalKey,
      tier: tier,
      seed: seed,
      suspect_id: suspectId,
      suspectId: suspectId,
      dept: dept,
      role: role,
      after_hours_count: afterHoursCount,
      afterHoursCount: afterHoursCount,
      demeanor: demeanor,
      demeanor_is_evidence: false,
      signal_calibrated: true,
      question: question,
      text: responseText,
      snippet: responseText,
      response: responseText,
      audit_note:
        "Deterministic non-leaking interview snippet: persona tone is stylistic atmosphere; rely on canary variant partitions and access logs rather than demeanor."
    };
  }

  function getWorkplaceChatter(rawOpts) {
    var clean = stripTruthFields(rawOpts);
    var tier = normalizeTier(firstDefined(clean, ["tier", "difficulty"]));
    var seed = normalizeInt(firstDefined(clean, ["seed", "world_seed", "worldSeed"]), 0);
    var count = normalizeInt(firstDefined(clean, ["chatterCount", "chatter_count", "count"]), 4, 1);
    var worldKey = tier + ":" + String(seed);
    var rng = createRng(fnv1a32("outthink-chatter|" + worldKey));
    var picked = pickDistinctIndices(SLACK_HALLWAY_POOL.length, Math.min(count, SLACK_HALLWAY_POOL.length), rng);
    var tierCtx = TIER_CONTEXT[tier] || TIER_CONTEXT.hard;
    var items = [];

    for (var i = 0; i < picked.length; i += 1) {
      var tpl = SLACK_HALLWAY_POOL[picked[i]];
      var dayNum = 1 + ((i + (rng() % 2)) % 4);
      items.push({
        id: "wt-chat-" + tier + "-" + String(seed) + "-" + String(i + 1),
        world_key: worldKey,
        tier: tier,
        seed: seed,
        day: dayNum,
        kind: tpl.kind,
        channel: tpl.channel,
        speaker_role: tpl.speaker_role,
        topic: tpl.topic,
        context_cadence: tierCtx.cadence,
        text: tpl.text,
        is_distractor: false,
        is_biased_rumor: false,
        evidentiary_weight: 0.0
      });
    }
    return items;
  }

  function getBiasRumorDistractors(rawOpts) {
    var clean = stripTruthFields(rawOpts);
    var tier = normalizeTier(firstDefined(clean, ["tier", "difficulty"]));
    var seed = normalizeInt(firstDefined(clean, ["seed", "world_seed", "worldSeed"]), 0);
    var rumorCount = normalizeInt(firstDefined(clean, ["rumorCount", "rumor_count"]), 2, 1);
    var worldKey = tier + ":" + String(seed);
    var rng = createRng(fnv1a32("outthink-rumors|" + worldKey));
    var picked = pickDistinctIndices(BIAS_RUMOR_POOL.length, Math.min(rumorCount, BIAS_RUMOR_POOL.length), rng);
    var items = [];

    for (var i = 0; i < picked.length; i += 1) {
      var tpl = BIAS_RUMOR_POOL[picked[i]];
      var dayNum = 2 + ((i + (rng() % 2)) % 4);
      items.push({
        id: "wt-rumor-" + tier + "-" + String(seed) + "-" + String(i + 1),
        world_key: worldKey,
        tier: tier,
        seed: seed,
        day: dayNum,
        kind: "rumor_distractor",
        label: "BIAS-FLAVOURED WORKPLACE RUMOR (DISTRACTOR)",
        badge: "BIAS DISTRACTOR - ZERO PARTITION EVIDENCE",
        is_distractor: true,
        is_biased_rumor: true,
        bias_type: tpl.bias_type,
        channel: tpl.channel,
        speaker_role: tpl.speaker_role,
        topic: tpl.topic,
        text: tpl.text,
        why_canary_beats_rumor: tpl.why_canary_beats_rumor,
        evidentiary_weight: 0.0
      });
    }
    return items;
  }

  function cloneProvenance() {
    return {
      environment_scope: PROVENANCE_STATS.environment_scope,
      role: PROVENANCE_STATS.role,
      model_id: PROVENANCE_STATS.model_id,
      tiers_version: PROVENANCE_STATS.tiers_version,
      verified_folders: PROVENANCE_STATS.verified_folders,
      verified_carbon_folders: PROVENANCE_STATS.verified_carbon_folders,
      calls: PROVENANCE_STATS.calls,
      api_calls: PROVENANCE_STATS.api_calls,
      input_tokens: PROVENANCE_STATS.input_tokens,
      output_tokens: PROVENANCE_STATS.output_tokens,
      thinking_tokens: PROVENANCE_STATS.thinking_tokens,
      cached_tokens: PROVENANCE_STATS.cached_tokens,
      cost_usd: PROVENANCE_STATS.cost_usd,
      personas: PROVENANCE_STATS.personas,
      unique_personas: PROVENANCE_STATS.unique_personas,
      worlds: PROVENANCE_STATS.worlds,
      unique_worlds: PROVENANCE_STATS.unique_worlds,
      worlds_by_tier: {
        easy: PROVENANCE_STATS.worlds_by_tier.easy,
        medium: PROVENANCE_STATS.worlds_by_tier.medium,
        hard: PROVENANCE_STATS.worlds_by_tier.hard
      },
      personas_by_tier: {
        easy: PROVENANCE_STATS.personas_by_tier.easy,
        medium: PROVENANCE_STATS.personas_by_tier.medium,
        hard: PROVENANCE_STATS.personas_by_tier.hard
      },
      live_interviews: PROVENANCE_STATS.live_interviews,
      interview_worlds: PROVENANCE_STATS.interview_worlds,
      interview_batches: PROVENANCE_STATS.interview_batches,
      signal_calibration_accuracy: PROVENANCE_STATS.signal_calibration_accuracy,
      signal_calibration_pct: PROVENANCE_STATS.signal_calibration_pct,
      signal_calibration_ci95: PROVENANCE_STATS.signal_calibration_ci95.slice(),
      counterfactual_checks: PROVENANCE_STATS.counterfactual_checks,
      counterfactual_invariance_rate: PROVENANCE_STATS.counterfactual_invariance_rate,
      counterfactual_invariance_ci95: PROVENANCE_STATS.counterfactual_invariance_ci95.slice(),
      biased_chatter_messages: PROVENANCE_STATS.biased_chatter_messages,
      live_llm_biased_messages: PROVENANCE_STATS.live_llm_biased_messages,
      ablation_episodes: PROVENANCE_STATS.ablation_episodes,
      paired_ablation_seeds: PROVENANCE_STATS.paired_ablation_seeds,
      solver_rumor_distraction_rate: PROVENANCE_STATS.solver_rumor_distraction_rate,
      carbon_rumor_distraction_rate: PROVENANCE_STATS.carbon_rumor_distraction_rate,
      carbon_false_rumor_accusation_rate: PROVENANCE_STATS.carbon_false_rumor_accusation_rate,
      dynamic_events: PROVENANCE_STATS.dynamic_events,
      dynamic_event_worlds: PROVENANCE_STATS.dynamic_event_worlds,
      thinking_calibrated_worlds: PROVENANCE_STATS.thinking_calibrated_worlds,
      encodings_scanned: PROVENANCE_STATS.encodings_scanned,
      supported_encodings_count: PROVENANCE_STATS.supported_encodings_count,
      leaks_detected: PROVENANCE_STATS.leaks_detected,
      truth_leak_violations: PROVENANCE_STATS.truth_leak_violations,
      prompt_truth_leak_violations: PROVENANCE_STATS.prompt_truth_leak_violations,
      lint_violations: PROVENANCE_STATS.lint_violations,
      stego_encoding_violations: PROVENANCE_STATS.stego_encoding_violations,
      fallback_count: PROVENANCE_STATS.fallback_count,
      all_clean: PROVENANCE_STATS.all_clean,
      summary_line: PROVENANCE_STATS.summary_line
    };
  }

  function getProvenanceSummary() {
    return cloneProvenance();
  }

  function getOutthinkChatter(rawOpts) {
    var clean = stripTruthFields(rawOpts);
    var tier = normalizeTier(firstDefined(clean, ["tier", "difficulty"]));
    var seed = normalizeInt(firstDefined(clean, ["seed", "world_seed", "worldSeed"]), 0);
    var suspectObj = isObject(clean.suspect) ? stripTruthFields(clean.suspect) : null;

    var suspectId = normalizeSuspectId(
      firstDefined(clean, ["suspectId", "suspect_id", "employeeId", "employee_id"]) ||
        (suspectObj && firstDefined(suspectObj, ["id", "suspectId", "suspect_id", "employeeId", "employee_id"])) ||
        firstDefined(clean, ["id"])
    );
    var dept = sanitizeLabel(
      firstDefined(clean, ["dept", "department", "team", "division"]) ||
        (suspectObj && firstDefined(suspectObj, ["dept", "department", "team", "division"])),
      "Operations"
    );
    var role = sanitizeLabel(
      firstDefined(clean, ["role", "job_title", "jobTitle", "title", "position"]) ||
        (suspectObj && firstDefined(suspectObj, ["role", "job_title", "jobTitle", "title", "position"])),
      "Staff Specialist"
    );
    var rawAh = firstDefined(clean, ["afterHoursCount", "after_hours_count", "afterHours", "after_hours"]);
    if (rawAh === undefined && suspectObj) {
      rawAh = firstDefined(suspectObj, ["afterHoursCount", "after_hours_count", "afterHours", "after_hours"]);
    }
    var afterHoursCount = normalizeInt(rawAh, 0, 0);

    var chatterItems = getWorkplaceChatter({
      tier: tier,
      seed: seed,
      chatterCount: firstDefined(clean, ["chatterCount", "chatter_count", "count"])
    });
    var rumorItems = getBiasRumorDistractors({
      tier: tier,
      seed: seed,
      rumorCount: firstDefined(clean, ["rumorCount", "rumor_count"])
    });
    var primaryInterview = getSuspectInterview({
      tier: tier,
      seed: seed,
      suspectId: suspectId,
      dept: dept,
      role: role,
      afterHoursCount: afterHoursCount
    });

    var interviewsBySuspect = {};
    interviewsBySuspect[primaryInterview.suspect_id] = primaryInterview;

    if (Array.isArray(clean.suspects)) {
      for (var i = 0; i < clean.suspects.length; i += 1) {
        var sItem = clean.suspects[i];
        if (!isObject(sItem)) {
          continue;
        }
        var cleanSuspect = stripTruthFields(sItem);
        var sid = normalizeSuspectId(
          firstDefined(cleanSuspect, ["id", "suspectId", "suspect_id", "employeeId", "employee_id"])
        );
        interviewsBySuspect[sid] = getSuspectInterview({
          tier: tier,
          seed: seed,
          suspectId: sid,
          dept: firstDefined(cleanSuspect, ["dept", "department", "team", "division"]) || dept,
          role: firstDefined(cleanSuspect, ["role", "job_title", "jobTitle", "title", "position"]) || role,
          afterHoursCount: firstDefined(cleanSuspect, [
            "afterHoursCount",
            "after_hours_count",
            "afterHours",
            "after_hours"
          ])
        });
      }
    }

    return {
      key: primaryInterview.key,
      world_key: tier + ":" + String(seed),
      tier: tier,
      seed: seed,
      suspect_id: suspectId,
      suspectId: suspectId,
      dept: dept,
      role: role,
      after_hours_count: afterHoursCount,
      afterHoursCount: afterHoursCount,
      chatter: chatterItems,
      slack_hallway_chatter: chatterItems,
      rumors: rumorItems,
      bias_rumor_distractors: rumorItems,
      canary_vs_rumor: {
        headline: CANARY_VS_RUMOR_EXPLAINER.headline,
        core_principle: CANARY_VS_RUMOR_EXPLAINER.core_principle,
        ablation_evidence: CANARY_VS_RUMOR_EXPLAINER.ablation_evidence,
        decision_rule: CANARY_VS_RUMOR_EXPLAINER.decision_rule
      },
      interview: primaryInterview,
      interviews_by_suspect: interviewsBySuspect,
      provenance: cloneProvenance()
    };
  }

  var OUTTHINK_CHATTER = {
    version: "1.0.0",
    environment_scope: SCOPE_LABEL,
    role: "world_text",
    model_id: "gemini-4-carbon",
    tiers_version: "v1.4",
    provenance: PROVENANCE_STATS,
    canary_vs_rumor_explainer: CANARY_VS_RUMOR_EXPLAINER,
    supported_encodings: SUPPORTED_ENCODINGS,
    slack_hallway_pool: SLACK_HALLWAY_POOL,
    bias_rumor_pool: BIAS_RUMOR_POOL,
    getOutthinkChatter: getOutthinkChatter,
    getSuspectInterview: getSuspectInterview,
    getWorkplaceChatter: getWorkplaceChatter,
    getBiasRumorDistractors: getBiasRumorDistractors,
    getProvenanceSummary: getProvenanceSummary
  };

  OUTTHINK_CHATTER.OUTTHINK_CHATTER = OUTTHINK_CHATTER;

  if (typeof window !== "undefined" && window) {
    window.OUTTHINK_CHATTER = OUTTHINK_CHATTER;
    window.getOutthinkChatter = getOutthinkChatter;
  }
  if (root && typeof root === "object") {
    root.OUTTHINK_CHATTER = OUTTHINK_CHATTER;
    root.getOutthinkChatter = getOutthinkChatter;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = OUTTHINK_CHATTER;
  }
})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);
