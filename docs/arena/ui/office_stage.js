export const TILE_SIZE = 16;
export const GRID_COLS = 40;
export const GRID_ROWS = 24;

const DEFAULT_CREDITS = "Procedural geometric pixel placeholders (Canary Arena Step 1, 0 external assets)";

const ZONE_LIST = [
  {
    id: "engineering",
    name: "Engineering",
    kind: "department",
    x: 1,
    y: 2,
    w: 12,
    h: 7,
    doorways: [
      { x: 5, y: 8 },
      { x: 6, y: 8 },
      { x: 12, y: 5 }
    ],
    accent: "rgb(56, 152, 236)",
    floorA: "rgb(26, 36, 52)",
    floorB: "rgb(30, 41, 58)"
  },
  {
    id: "research",
    name: "Research",
    kind: "department",
    x: 14,
    y: 2,
    w: 12,
    h: 7,
    doorways: [
      { x: 19, y: 8 },
      { x: 20, y: 8 },
      { x: 14, y: 5 },
      { x: 25, y: 5 }
    ],
    accent: "rgb(46, 196, 198)",
    floorA: "rgb(24, 40, 48)",
    floorB: "rgb(28, 45, 54)"
  },
  {
    id: "finance",
    name: "Finance",
    kind: "department",
    x: 27,
    y: 2,
    w: 12,
    h: 7,
    doorways: [
      { x: 32, y: 8 },
      { x: 33, y: 8 },
      { x: 27, y: 5 }
    ],
    accent: "rgb(52, 188, 122)",
    floorA: "rgb(24, 40, 36)",
    floorB: "rgb(28, 46, 41)"
  },
  {
    id: "sales",
    name: "Sales",
    kind: "department",
    x: 1,
    y: 11,
    w: 12,
    h: 6,
    doorways: [
      { x: 6, y: 11 },
      { x: 7, y: 11 },
      { x: 6, y: 16 },
      { x: 7, y: 16 },
      { x: 12, y: 13 }
    ],
    accent: "rgb(238, 146, 54)",
    floorA: "rgb(42, 34, 28)",
    floorB: "rgb(48, 39, 32)"
  },
  {
    id: "legal",
    name: "Legal",
    kind: "department",
    x: 14,
    y: 11,
    w: 12,
    h: 6,
    doorways: [
      { x: 19, y: 11 },
      { x: 20, y: 11 },
      { x: 19, y: 16 },
      { x: 20, y: 16 },
      { x: 14, y: 13 },
      { x: 25, y: 13 }
    ],
    accent: "rgb(166, 110, 228)",
    floorA: "rgb(36, 30, 48)",
    floorB: "rgb(42, 35, 55)"
  },
  {
    id: "coffee_corner",
    name: "Coffee Corner",
    kind: "facility",
    x: 27,
    y: 11,
    w: 12,
    h: 6,
    doorways: [
      { x: 32, y: 11 },
      { x: 33, y: 11 },
      { x: 32, y: 16 },
      { x: 33, y: 16 },
      { x: 27, y: 13 },
      { x: 27, y: 14 }
    ],
    accent: "rgb(218, 162, 92)",
    floorA: "rgb(48, 38, 30)",
    floorB: "rgb(55, 44, 35)"
  },
  {
    id: "meeting_room_a",
    name: "Meeting Room A",
    kind: "facility",
    x: 1,
    y: 18,
    w: 9,
    h: 5,
    doorways: [
      { x: 4, y: 18 },
      { x: 5, y: 18 }
    ],
    accent: "rgb(102, 168, 224)",
    floorA: "rgb(28, 36, 48)",
    floorB: "rgb(33, 42, 56)"
  },
  {
    id: "meeting_room_b",
    name: "Meeting Room B",
    kind: "facility",
    x: 11,
    y: 18,
    w: 9,
    h: 5,
    doorways: [
      { x: 14, y: 18 },
      { x: 15, y: 18 }
    ],
    accent: "rgb(120, 184, 164)",
    floorA: "rgb(28, 38, 44)",
    floorB: "rgb(33, 44, 50)"
  },
  {
    id: "security_desk",
    name: "Security Desk",
    kind: "facility",
    x: 21,
    y: 18,
    w: 9,
    h: 5,
    doorways: [
      { x: 24, y: 18 },
      { x: 25, y: 18 }
    ],
    accent: "rgb(232, 94, 94)",
    floorA: "rgb(38, 28, 34)",
    floorB: "rgb(44, 33, 40)"
  },
  {
    id: "server_room",
    name: "Server Room",
    kind: "facility",
    x: 31,
    y: 18,
    w: 8,
    h: 5,
    doorways: [
      { x: 34, y: 18 },
      { x: 35, y: 18 }
    ],
    accent: "rgb(72, 214, 152)",
    floorA: "rgb(18, 28, 34)",
    floorB: "rgb(22, 34, 40)"
  }
];

function createZonesRegistry() {
  const reg = {};
  for (const z of ZONE_LIST) {
    reg[z.name] = Object.freeze({
      ...z,
      doorways: Object.freeze(z.doorways.map((d) => Object.freeze({ ...d })))
    });
  }
  Object.defineProperty(reg, Symbol.iterator, {
    enumerable: false,
    value: function* iterateZones() {
      for (const z of ZONE_LIST) {
        yield reg[z.name];
      }
    }
  });
  return Object.freeze(reg);
}

export const OFFICE_ZONES = createZonesRegistry();

const DEPT_NAMES = ["Engineering", "Finance", "Legal", "Research", "Sales"];

const SKIN_TONES = [
  "rgb(244, 206, 178)",
  "rgb(228, 184, 148)",
  "rgb(198, 146, 108)",
  "rgb(162, 110, 76)",
  "rgb(122, 78, 54)",
  "rgb(236, 196, 166)"
];

const HAIR_COLORS = [
  "rgb(36, 32, 38)",
  "rgb(88, 56, 38)",
  "rgb(152, 98, 52)",
  "rgb(212, 172, 92)",
  "rgb(164, 62, 48)",
  "rgb(72, 82, 98)",
  "rgb(214, 218, 226)"
];

const VARIANT_PALETTE = {
  A: { fill: "rgb(66, 184, 246)", ink: "rgb(12, 26, 42)" },
  B: { fill: "rgb(246, 192, 68)", ink: "rgb(38, 26, 8)" },
  C: { fill: "rgb(238, 98, 156)", ink: "rgb(42, 10, 24)" },
  D: { fill: "rgb(112, 222, 138)", ink: "rgb(12, 36, 18)" },
  E: { fill: "rgb(178, 132, 246)", ink: "rgb(26, 12, 44)" }
};

const FORBIDDEN_TRUTH_KEYS = new Set([
  "mole",
  "moleId",
  "mole_id",
  "true_mole",
  "is_mole",
  "_world",
  "world_seed",
  "mole_strategy",
  "secret",
  "world_secret",
  "CANARY_WORLD_SECRET"
]);

let sharedSpritePack = null;

function hashString(input) {
  const str = String(input || "");
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function isInspectableObject(val) {
  if (!val || typeof val !== "object") {
    return false;
  }
  if (Array.isArray(val)) {
    return true;
  }
  if (
    typeof val.getContext === "function" ||
    typeof val.fillRect === "function" ||
    typeof val.nodeType === "number" ||
    typeof val.addEventListener === "function"
  ) {
    return false;
  }
  return true;
}

function scanForbiddenTruth(node, depth = 0) {
  if (depth > 8 || !isInspectableObject(node)) {
    return null;
  }
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i += 1) {
      const hit = scanForbiddenTruth(node[i], depth + 1);
      if (hit) {
        return hit;
      }
    }
    return null;
  }
  const keys = Object.keys(node);
  for (let i = 0; i < keys.length; i += 1) {
    const k = keys[i];
    if (FORBIDDEN_TRUTH_KEYS.has(k)) {
      return k;
    }
    const child = node[k];
    if (isInspectableObject(child)) {
      const hit = scanForbiddenTruth(child, depth + 1);
      if (hit) {
        return hit;
      }
    }
  }
  return null;
}

function assertPublicIntegrity(payload, mode, episodeDone, contextLabel) {
  if (episodeDone === true || mode === "mole") {
    return;
  }
  if (!payload || typeof payload !== "object") {
    return;
  }
  const hitKey = scanForbiddenTruth(payload, 0);
  if (hitKey) {
    throw new Error(
      `OfficeStage integrity violation in ${contextLabel}: forbidden hidden-truth field "${hitKey}" while episodeDone is false and mode !== "mole"`
    );
  }
  const evName = String(payload.type || payload.tool || payload.event || "");
  if (evName === "mole" || evName === "_world" || evName === "secret" || evName === "mole_leak") {
    throw new Error(
      `OfficeStage integrity violation in ${contextLabel}: forbidden event "${evName}" while episodeDone is false and mode !== "mole"`
    );
  }
}

function computeEmployeeVisual(emp) {
  const id = String(emp.id || "e00");
  const dept = String(emp.dept || "Engineering");
  const role = String(emp.role || "staff");
  const seed = hashString(`${id}|${dept}|${role}`);
  const zone = OFFICE_ZONES[dept] || OFFICE_ZONES.Engineering;
  const skin = SKIN_TONES[seed % SKIN_TONES.length];
  const hair = HAIR_COLORS[(seed >>> 3) % HAIR_COLORS.length];
  const hairStyle = (seed >>> 7) % 4;
  const roleLower = role.toLowerCase();
  let badgePips = 1;
  if (
    roleLower.includes("lead") ||
    roleLower.includes("manager") ||
    roleLower.includes("controller") ||
    roleLower.includes("counsel")
  ) {
    badgePips = 3;
  } else if (
    roleLower.includes("senior") ||
    roleLower.includes("scientist") ||
    roleLower.includes("compliance")
  ) {
    badgePips = 2;
  }
  return {
    id,
    name: String(emp.name || id),
    dept,
    role,
    jacket: zone.accent,
    skin,
    hair,
    hairStyle,
    badgePips,
    seed
  };
}

function buildZoneDeskSlots(zone) {
  const rowOffsets = zone.h >= 7 ? [1, 4] : [1, 3];
  const primaryCols = [1, 4, 7, 10];
  const flexCols = [2, 5, 8];
  const slots = [];
  for (let r = 0; r < rowOffsets.length; r += 1) {
    const deskY = zone.y + rowOffsets[r];
    const chairY = deskY + 1;
    for (let c = 0; c < primaryCols.length; c += 1) {
      const deskX = zone.x + primaryCols[c];
      slots.push({
        zone: zone.name,
        x: deskX,
        y: deskY,
        chairX: deskX,
        chairY,
        primary: true
      });
    }
  }
  for (let r = 0; r < rowOffsets.length; r += 1) {
    const deskY = zone.y + rowOffsets[r];
    const chairY = deskY + 1;
    for (let c = 0; c < flexCols.length; c += 1) {
      const deskX = zone.x + flexCols[c];
      slots.push({
        zone: zone.name,
        x: deskX,
        y: deskY,
        chairX: deskX,
        chairY,
        primary: false
      });
    }
  }
  return slots;
}

export function buildOfficeMap(staffList = []) {
  const grid = Array.from({ length: GRID_ROWS }, () =>
    Array.from({ length: GRID_COLS }, () => "wall")
  );
  const walkable = Array.from({ length: GRID_ROWS }, () =>
    Array.from({ length: GRID_COLS }, () => false)
  );

  for (let x = 1; x < GRID_COLS - 1; x += 1) {
    grid[1][x] = "window";
  }

  const corridors = [];
  const markCorridor = (x, y) => {
    if (x >= 1 && x < GRID_COLS - 1 && y >= 2 && y < GRID_ROWS - 1) {
      grid[y][x] = "corridor";
      walkable[y][x] = true;
      corridors.push({ x, y });
    }
  };

  for (let x = 1; x <= 38; x += 1) {
    markCorridor(x, 9);
    markCorridor(x, 10);
    markCorridor(x, 17);
  }
  for (let y = 2; y <= 17; y += 1) {
    markCorridor(13, y);
    markCorridor(26, y);
  }
  for (let y = 17; y <= 22; y += 1) {
    markCorridor(10, y);
    markCorridor(20, y);
    markCorridor(30, y);
  }

  for (const z of ZONE_LIST) {
    const doorSet = new Set(z.doorways.map((d) => `${d.x},${d.y}`));
    for (let y = z.y; y < z.y + z.h; y += 1) {
      for (let x = z.x; x < z.x + z.w; x += 1) {
        const onLeft = x === z.x && z.x > 1;
        const onRight = x === z.x + z.w - 1 && z.x + z.w - 1 < 38;
        const onTop = y === z.y && z.y > 2;
        const onBottom = y === z.y + z.h - 1 && z.y + z.h - 1 < 22;
        const isBorder = onLeft || onRight || onTop || onBottom;
        if (doorSet.has(`${x},${y}`)) {
          grid[y][x] = "door";
          walkable[y][x] = true;
        } else if (isBorder) {
          grid[y][x] = "partition";
          walkable[y][x] = false;
        } else {
          grid[y][x] = z.kind === "department" ? "dept_floor" : "facility_floor";
          walkable[y][x] = true;
        }
      }
    }
    for (const d of z.doorways) {
      grid[d.y][d.x] = "door";
      walkable[d.y][d.x] = true;
    }
  }

  const blockProp = (x, y, kind) => {
    if (y >= 0 && y < GRID_ROWS && x >= 0 && x < GRID_COLS) {
      grid[y][x] = kind;
      walkable[y][x] = false;
    }
  };

  for (let x = 34; x <= 37; x += 1) {
    blockProp(x, 12, "coffee_bar");
  }
  blockProp(29, 13, "bistro_table");
  blockProp(34, 14, "bistro_table");

  for (let x = 3; x <= 6; x += 1) {
    blockProp(x, 20, "meeting_table");
  }
  for (let x = 13; x <= 16; x += 1) {
    blockProp(x, 20, "meeting_table");
  }
  for (let x = 24; x <= 26; x += 1) {
    blockProp(x, 20, "security_console");
  }
  for (let y = 19; y <= 21; y += 1) {
    blockProp(32, y, "server_rack");
    blockProp(37, y, "server_rack");
  }

  const slotsByDept = {};
  for (let i = 0; i < DEPT_NAMES.length; i += 1) {
    const deptName = DEPT_NAMES[i];
    slotsByDept[deptName] = buildZoneDeskSlots(OFFICE_ZONES[deptName]);
  }

  const normalizedStaff = Array.isArray(staffList) ? staffList : [];
  const usedSlotKeys = new Set();
  const desks = [];
  const deskByEmployee = {};

  const claimSlot = (slot, emp) => {
    const key = `${slot.x},${slot.y}`;
    usedSlotKeys.add(key);
    const deskRecord = {
      id: `desk_${desks.length}`,
      zone: slot.zone,
      x: slot.x,
      y: slot.y,
      chairX: slot.chairX,
      chairY: slot.chairY,
      primary: slot.primary,
      employeeId: emp ? String(emp.id) : null
    };
    desks.push(deskRecord);
    blockProp(slot.x, slot.y, "desk");
    walkable[slot.chairY][slot.chairX] = true;
    if (grid[slot.chairY][slot.chairX] === "partition") {
      grid[slot.chairY][slot.chairX] = "dept_floor";
    }
    if (emp) {
      deskByEmployee[String(emp.id)] = deskRecord;
    }
    return deskRecord;
  };

  for (let i = 0; i < DEPT_NAMES.length; i += 1) {
    const deptName = DEPT_NAMES[i];
    const slots = slotsByDept[deptName];
    for (let s = 0; s < slots.length; s += 1) {
      if (slots[s].primary) {
        claimSlot(slots[s], null);
      }
    }
  }

  const openDesksByDept = {};
  for (let i = 0; i < DEPT_NAMES.length; i += 1) {
    const dName = DEPT_NAMES[i];
    openDesksByDept[dName] = desks.filter((d) => d.zone === dName && d.employeeId === null);
  }

  const overflowEmployees = [];
  for (let i = 0; i < normalizedStaff.length; i += 1) {
    const emp = normalizedStaff[i];
    if (!emp || emp.id === undefined || emp.id === null) {
      continue;
    }
    const dept = DEPT_NAMES.includes(emp.dept) ? emp.dept : DEPT_NAMES[i % DEPT_NAMES.length];
    const deptOpen = openDesksByDept[dept];
    if (deptOpen && deptOpen.length > 0) {
      const targetDesk = deptOpen.shift();
      targetDesk.employeeId = String(emp.id);
      deskByEmployee[String(emp.id)] = targetDesk;
    } else {
      const extraSlots = slotsByDept[dept] || [];
      let placedFlex = false;
      for (let s = 0; s < extraSlots.length; s += 1) {
        const cand = extraSlots[s];
        if (!usedSlotKeys.has(`${cand.x},${cand.y}`)) {
          claimSlot(cand, emp);
          placedFlex = true;
          break;
        }
      }
      if (!placedFlex) {
        overflowEmployees.push(emp);
      }
    }
  }

  for (let i = 0; i < overflowEmployees.length; i += 1) {
    const emp = overflowEmployees[i];
    let fallbackDesk = desks.find((d) => d.employeeId === null);
    if (!fallbackDesk) {
      for (let d = 0; d < DEPT_NAMES.length; d += 1) {
        const extra = slotsByDept[DEPT_NAMES[d]];
        const freeSlot = extra.find((s) => !usedSlotKeys.has(`${s.x},${s.y}`));
        if (freeSlot) {
          fallbackDesk = claimSlot(freeSlot, emp);
          break;
        }
      }
    } else {
      fallbackDesk.employeeId = String(emp.id);
      deskByEmployee[String(emp.id)] = fallbackDesk;
    }
  }

  const waypoints = {
    "Coffee Corner": [
      { x: 30, y: 13 },
      { x: 31, y: 13 },
      { x: 31, y: 14 },
      { x: 32, y: 14 },
      { x: 35, y: 13 },
      { x: 36, y: 14 }
    ],
    "Meeting Room A": [
      { x: 4, y: 19 },
      { x: 5, y: 19 },
      { x: 4, y: 21 },
      { x: 5, y: 21 }
    ],
    "Meeting Room B": [
      { x: 14, y: 19 },
      { x: 15, y: 19 },
      { x: 14, y: 21 },
      { x: 15, y: 21 }
    ],
    "Security Desk": [
      { x: 25, y: 19 },
      { x: 25, y: 21 },
      { x: 23, y: 20 },
      { x: 27, y: 20 }
    ],
    "Server Room": [
      { x: 34, y: 19 },
      { x: 35, y: 19 },
      { x: 34, y: 20 },
      { x: 35, y: 20 },
      { x: 34, y: 21 }
    ],
    corridorHubs: [
      { x: 13, y: 9 },
      { x: 26, y: 9 },
      { x: 13, y: 17 },
      { x: 26, y: 17 },
      { x: 20, y: 10 }
    ]
  };

  return {
    width: GRID_COLS,
    height: GRID_ROWS,
    tileSize: TILE_SIZE,
    zones: OFFICE_ZONES,
    zoneList: ZONE_LIST.map((z) => OFFICE_ZONES[z.name]),
    grid,
    walkable,
    corridors,
    desks,
    deskByEmployee,
    waypoints
  };
}

export function findWalkPath(officeMap, start, goal) {
  const sx = Math.max(0, Math.min(GRID_COLS - 1, Math.round(start.x)));
  const sy = Math.max(0, Math.min(GRID_ROWS - 1, Math.round(start.y)));
  const gx = Math.max(0, Math.min(GRID_COLS - 1, Math.round(goal.x)));
  const gy = Math.max(0, Math.min(GRID_ROWS - 1, Math.round(goal.y)));
  if (sx === gx && sy === gy) {
    return [{ x: sx, y: sy }];
  }
  const visited = Array.from({ length: GRID_ROWS }, () =>
    Array.from({ length: GRID_COLS }, () => false)
  );
  const parent = new Map();
  const queue = [{ x: sx, y: sy }];
  visited[sy][sx] = true;
  const dirs = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1]
  ];
  let head = 0;
  while (head < queue.length) {
    const cur = queue[head];
    head += 1;
    if (cur.x === gx && cur.y === gy) {
      const path = [];
      let node = cur;
      while (node) {
        path.push({ x: node.x, y: node.y });
        node = parent.get(`${node.x},${node.y}`) || null;
      }
      path.reverse();
      return path;
    }
    for (let i = 0; i < dirs.length; i += 1) {
      const nx = cur.x + dirs[i][0];
      const ny = cur.y + dirs[i][1];
      if (nx < 0 || nx >= GRID_COLS || ny < 0 || ny >= GRID_ROWS) {
        continue;
      }
      if (visited[ny][nx]) {
        continue;
      }
      const canStep = officeMap.walkable[ny][nx] || (nx === gx && ny === gy);
      if (!canStep) {
        continue;
      }
      visited[ny][nx] = true;
      parent.set(`${nx},${ny}`, cur);
      queue.push({ x: nx, y: ny });
    }
  }
  return [
    { x: sx, y: sy },
    { x: gx, y: gy }
  ];
}

function joinAssetUrl(baseUrl, relPath) {
  if (!relPath) {
    return "";
  }
  if (!baseUrl) {
    return String(relPath);
  }
  const cleanBase = String(baseUrl).replace(/\/+$/, "");
  const cleanRel = String(relPath).replace(/^\/+/, "");
  return `${cleanBase}/${cleanRel}`;
}

function loadImageSheet(src, customLoader) {
  if (!src) {
    return Promise.resolve(null);
  }
  if (typeof customLoader === "function") {
    return Promise.resolve(customLoader(src));
  }
  if (typeof Image === "function") {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`Failed to load sprite sheet: ${src}`));
      img.src = src;
    });
  }
  return Promise.resolve({ src, loaded: true, headless: true });
}

async function resolveSpritePackManifest(manifest) {
  if (!manifest || typeof manifest !== "object") {
    throw new Error("loadSpritePack requires a manifest object");
  }
  const sheets = manifest.sheets && typeof manifest.sheets === "object" ? manifest.sheets : {};
  const rawTileSheet =
    manifest.tileSheet || sheets.tiles || sheets.indoors || sheets.tileSheet || "";
  const rawCharSheet =
    manifest.charSheet || sheets.characters || sheets.chars || sheets.charSheet || "";
  const tileUrl = joinAssetUrl(manifest.baseUrl, rawTileSheet);
  const charUrl = joinAssetUrl(manifest.baseUrl, rawCharSheet);
  const [tileImage, charImage] = await Promise.all([
    loadImageSheet(tileUrl, manifest.imageLoader),
    loadImageSheet(charUrl, manifest.imageLoader)
  ]);
  let resolvedCredits = DEFAULT_CREDITS;
  if (manifest.creditsText) {
    resolvedCredits = String(manifest.creditsText);
  } else if (typeof manifest.attribution === "string" && manifest.attribution) {
    resolvedCredits = manifest.attribution;
  } else if (
    manifest.attribution &&
    typeof manifest.attribution === "object" &&
    manifest.attribution.creditsText
  ) {
    resolvedCredits = String(manifest.attribution.creditsText);
  } else if (
    manifest.attribution &&
    typeof manifest.attribution === "object" &&
    manifest.attribution.text
  ) {
    resolvedCredits = String(manifest.attribution.text);
  }
  const mergedSprites = {
    ...(manifest.item_sprites && typeof manifest.item_sprites === "object"
      ? manifest.item_sprites
      : {}),
    ...(manifest.sprites && typeof manifest.sprites === "object" ? manifest.sprites : {})
  };
  return {
    loaded: true,
    baseUrl: String(manifest.baseUrl || ""),
    tileSheet: String(rawTileSheet),
    charSheet: String(rawCharSheet),
    tileUrl,
    charUrl,
    tileImage,
    charImage,
    frameW: Number(manifest.frameW) > 0 ? Number(manifest.frameW) : TILE_SIZE,
    frameH: Number(manifest.frameH) > 0 ? Number(manifest.frameH) : TILE_SIZE,
    creditsText: resolvedCredits,
    sprites: mergedSprites,
    employees:
      manifest.employees && typeof manifest.employees === "object" ? { ...manifest.employees } : {}
  };
}

function computeClockPhase(actionsUsed, perDay) {
  const denom = Number(perDay) > 0 ? Number(perDay) : 8;
  const used = Math.max(0, Number(actionsUsed) || 0);
  const ratio = Math.min(1, used / denom);
  if (ratio < 0.25) {
    return "morning";
  }
  if (ratio < 0.625) {
    return "afternoon";
  }
  if (ratio < 0.875) {
    return "dusk";
  }
  return "night";
}

function createHeadlessContext() {
  const ops = [];
  return {
    fillStyle: "rgb(0, 0, 0)",
    strokeStyle: "rgb(0, 0, 0)",
    lineWidth: 1,
    font: "8px monospace",
    textAlign: "left",
    textBaseline: "alphabetic",
    imageSmoothingEnabled: false,
    _ops: ops,
    save() {
      ops.push("save");
    },
    restore() {
      ops.push("restore");
    },
    scale(sx, sy) {
      ops.push(["scale", sx, sy]);
    },
    clearRect(x, y, w, h) {
      ops.push(["clearRect", x, y, w, h]);
    },
    fillRect(x, y, w, h) {
      ops.push(["fillRect", x, y, w, h]);
    },
    strokeRect(x, y, w, h) {
      ops.push(["strokeRect", x, y, w, h]);
    },
    beginPath() {
      ops.push("beginPath");
    },
    closePath() {
      ops.push("closePath");
    },
    moveTo(x, y) {
      ops.push(["moveTo", x, y]);
    },
    lineTo(x, y) {
      ops.push(["lineTo", x, y]);
    },
    arc(x, y, r, s, e) {
      ops.push(["arc", x, y, r, s, e]);
    },
    fill() {
      ops.push("fill");
    },
    stroke() {
      ops.push("stroke");
    },
    fillText(txt, x, y) {
      ops.push(["fillText", String(txt), x, y]);
    },
    drawImage(...args) {
      ops.push(["drawImage", ...args]);
    }
  };
}

export class OfficeStage {
  constructor(canvasOrOptions = null, maybeOptions = {}) {
    let canvas = null;
    let opts = maybeOptions || {};
    if (
      canvasOrOptions &&
      typeof canvasOrOptions === "object" &&
      typeof canvasOrOptions.getContext !== "function" &&
      !canvasOrOptions.style
    ) {
      opts = canvasOrOptions;
      canvas = opts.canvas || null;
    } else {
      canvas = canvasOrOptions;
    }

    const initMode = opts && typeof opts.mode === "string" ? opts.mode : "investigator";
    const initDone = Boolean(opts && opts.episodeDone === true);
    assertPublicIntegrity(opts, initMode, initDone, "init");

    this.tileSize = TILE_SIZE;
    this.cols = GRID_COLS;
    this.rows = GRID_ROWS;
    this.logicalWidth = GRID_COLS * TILE_SIZE;
    this.logicalHeight = GRID_ROWS * TILE_SIZE;
    this.canvas = canvas;
    this.ctx =
      (opts && opts.ctx) ||
      (canvas && typeof canvas.getContext === "function" ? canvas.getContext("2d") : null) ||
      createHeadlessContext();

    if (this.canvas) {
      if (!this.canvas.width) {
        this.canvas.width = this.logicalWidth;
      }
      if (!this.canvas.height) {
        this.canvas.height = this.logicalHeight;
      }
      if (this.canvas.style && typeof this.canvas.style === "object") {
        this.canvas.style.imageRendering = "pixelated";
      }
    }
    if (this.ctx) {
      this.ctx.imageSmoothingEnabled = false;
    }

    this.spritePack = sharedSpritePack;
    this._rafId = null;
    this._timerId = null;
    this._running = false;
    this._destroyed = false;
    this._lastNow = 0;
    this.frameCount = 0;

    this.init(opts);
  }

  init(opts = {}) {
    const nextMode = typeof opts.mode === "string" ? opts.mode : this.mode || "investigator";
    const nextDone = opts.episodeDone !== undefined ? Boolean(opts.episodeDone) : false;
    assertPublicIntegrity(opts, nextMode, nextDone, "init");

    this.mode = nextMode;
    this.episodeDone = nextDone;
    this.timeMs = 0;
    this.strollTick = 0;

    this.clock = {
      day: 1,
      nDays: Number(opts.nDays) > 0 ? Number(opts.nDays) : 21,
      actionsUsed: 0,
      perDay: Number(opts.perDay) > 0 ? Number(opts.perDay) : 8,
      V: 1.0,
      phase: "morning"
    };
    this.overnightPulse = 0;

    this.staff = [];
    this.actors = new Map();
    this.restrictedIds = new Set();
    this.deskCanaries = new Map();
    this.canariesById = new Map();
    this.highlightedVariantDesks = new Set();
    this.leakBanner = { active: false, timerMs: 0, count: 0, lastLabel: "" };
    this.afterHoursMarks = new Map();
    this.serverAlertTimerMs = 0;
    this.activeInterview = null;
    this.socialInteractions = [];
    this.accusedId = null;
    this.revealedOutcome = null;
    this.humanMole = null;

    this.investigator = {
      x: 25,
      y: 21,
      homeX: 25,
      homeY: 21,
      path: [],
      speedTilesPerSec: 6.5
    };

    const initialStaff = Array.isArray(opts.staff) ? opts.staff : [];
    this._rebuildStaffAndMap(initialStaff);
    if (opts.clock && typeof opts.clock === "object") {
      this.setClock(opts.clock);
    }
    return this;
  }

  reset(opts = {}) {
    return this.init(opts);
  }

  _rebuildStaffAndMap(staffList) {
    assertPublicIntegrity({ staff: staffList }, this.mode, this.episodeDone, "list_employees");
    this.staff = staffList.map((emp) => ({
      id: String(emp.id),
      name: String(emp.name || emp.id),
      dept: String(emp.dept || "Engineering"),
      role: String(emp.role || "staff"),
      ...(emp.clearance !== undefined ? { clearance: emp.clearance } : {})
    }));
    this.map = buildOfficeMap(this.staff);
    this.actors.clear();
    for (let i = 0; i < this.staff.length; i += 1) {
      const emp = this.staff[i];
      const desk = this.map.deskByEmployee[emp.id] || this.map.desks[i % this.map.desks.length];
      const visual = computeEmployeeVisual(emp);
      this.actors.set(emp.id, {
        ...visual,
        homeX: desk.chairX,
        homeY: desk.chairY,
        deskX: desk.x,
        deskY: desk.y,
        zone: desk.zone,
        x: desk.chairX,
        y: desk.chairY,
        path: [],
        walkPhase: 0,
        dwellMs: 1200 + (visual.seed % 2800),
        state: "desk"
      });
    }
  }

  setMode(mode) {
    this.mode = String(mode || "investigator");
    if (this.mode !== "mole") {
      this.humanMole = null;
    }
    return this.mode;
  }

  setEpisodeDone(done) {
    this.episodeDone = Boolean(done);
    if (!this.episodeDone) {
      this.revealedOutcome = null;
    }
    return this.episodeDone;
  }

  async loadSpritePack(manifest) {
    const pack = await resolveSpritePackManifest(manifest);
    this.spritePack = pack;
    sharedSpritePack = pack;
    return pack;
  }

  getCreditsText() {
    if (this.spritePack && this.spritePack.creditsText) {
      return this.spritePack.creditsText;
    }
    if (sharedSpritePack && sharedSpritePack.creditsText) {
      return sharedSpritePack.creditsText;
    }
    return DEFAULT_CREDITS;
  }

  setClock(clockInput = {}) {
    const prevDay = this.clock ? this.clock.day : 1;
    const day = clockInput.day !== undefined ? Math.max(1, Number(clockInput.day) || 1) : prevDay;
    const nDays =
      clockInput.nDays !== undefined
        ? Math.max(1, Number(clockInput.nDays) || 21)
        : this.clock.nDays;
    const perDay =
      clockInput.perDay !== undefined
        ? Math.max(1, Number(clockInput.perDay) || 8)
        : this.clock.perDay;
    const actionsUsed =
      clockInput.actionsUsed !== undefined
        ? Math.max(0, Number(clockInput.actionsUsed) || 0)
        : this.clock.actionsUsed;
    const V =
      clockInput.V !== undefined
        ? Math.max(0, Math.min(1, Number(clockInput.V)))
        : this.clock.V;
    const phase =
      typeof clockInput.phase === "string" &&
      ["morning", "afternoon", "dusk", "night"].includes(clockInput.phase)
        ? clockInput.phase
        : computeClockPhase(actionsUsed, perDay);

    if (day > prevDay) {
      this.overnightPulse = 1.0;
    }
    this.clock = { day, nDays, actionsUsed, perDay, V, phase };
    return { ...this.clock };
  }

  _moveActorTo(actor, targetX, targetY, nextState = "walking") {
    if (!actor) {
      return;
    }
    const path = findWalkPath(this.map, { x: actor.x, y: actor.y }, { x: targetX, y: targetY });
    actor.path = path.slice(1);
    actor.state = nextState;
  }

  applyObservableEvent(evt) {
    if (!evt || typeof evt !== "object") {
      throw new Error("applyObservableEvent requires an event object");
    }
    assertPublicIntegrity(evt, this.mode, this.episodeDone, "applyObservableEvent");

    const kind = String(evt.type || evt.tool || evt.event || "");
    const args = evt.args && typeof evt.args === "object" ? evt.args : {};
    const resObj = evt.result && typeof evt.result === "object" ? evt.result : null;
    if (resObj && resObj.ok === false) {
      return { handled: false, kind };
    }
    const data =
      (evt.data && typeof evt.data === "object" ? evt.data : null) ||
      (resObj && resObj.data && typeof resObj.data === "object" ? resObj.data : {}) ||
      {};

    if (kind === "list_employees") {
      const emps = Array.isArray(evt.employees)
        ? evt.employees
        : Array.isArray(data.employees)
          ? data.employees
          : [];
      this._rebuildStaffAndMap(emps);
      return { handled: true, kind, count: this.staff.length };
    }

    if (kind === "plant_canary") {
      const assignment =
        (evt.assignment && typeof evt.assignment === "object" ? evt.assignment : null) ||
        (args.assignment && typeof args.assignment === "object" ? args.assignment : null) ||
        {};
      const canaryId = String(
        evt.canary_id || data.canary_id || evt.doc_id || `c${this.clock.day}_${this.canariesById.size + 1}`
      );
      const docTitle = String(evt.doc_title || args.doc_title || canaryId);
      const groups = {};
      const empIds = Object.keys(assignment);
      for (let i = 0; i < empIds.length; i += 1) {
        const empId = empIds[i];
        const variant = String(assignment[empId]);
        if (!groups[variant]) {
          groups[variant] = [];
        }
        groups[variant].push(empId);
        this.deskCanaries.set(empId, { canaryId, variant, docTitle, day: this.clock.day });
      }
      if (data.variants && typeof data.variants === "object") {
        const vKeys = Object.keys(data.variants);
        for (let i = 0; i < vKeys.length; i += 1) {
          const vLabel = vKeys[i];
          const members = Array.isArray(data.variants[vLabel]) ? data.variants[vLabel] : [];
          groups[vLabel] = members.slice();
          for (let m = 0; m < members.length; m += 1) {
            this.deskCanaries.set(String(members[m]), {
              canaryId,
              variant: vLabel,
              docTitle,
              day: this.clock.day
            });
          }
        }
      }
      this.canariesById.set(canaryId, { canaryId, docTitle, day: this.clock.day, groups });
      this.setClock({ actionsUsed: this.clock.actionsUsed + 1 });
      return { handled: true, kind, canaryId, recipients: empIds.length };
    }

    if (kind === "check_leak_feed") {
      const items = Array.isArray(evt.items)
        ? evt.items
        : Array.isArray(data.items)
          ? data.items
          : [];
      this.highlightedVariantDesks.clear();
      let lastLabel = "";
      for (let i = 0; i < items.length; i += 1) {
        const it = items[i] || {};
        const docId = String(it.doc_id || "");
        const variant = it.variant !== undefined ? String(it.variant) : "";
        if (variant) {
          lastLabel = `${docId}:${variant}`;
        } else if (docId) {
          lastLabel = docId;
        }
        const canaryRec = this.canariesById.get(docId);
        if (canaryRec && variant && Array.isArray(canaryRec.groups[variant])) {
          const groupMembers = canaryRec.groups[variant];
          for (let m = 0; m < groupMembers.length; m += 1) {
            this.highlightedVariantDesks.add(String(groupMembers[m]));
          }
        } else if (variant) {
          for (const [empId, cInfo] of this.deskCanaries.entries()) {
            if (cInfo.variant === variant && (!docId || cInfo.canaryId === docId)) {
              this.highlightedVariantDesks.add(empId);
            }
          }
        }
      }
      this.leakBanner = {
        active: items.length > 0 || Boolean(evt.pulse),
        timerMs: 3600,
        count: items.length,
        lastLabel
      };
      this.setClock({ actionsUsed: this.clock.actionsUsed + 1 });
      return {
        handled: true,
        kind,
        leaks: items.length,
        highlightedDesks: this.highlightedVariantDesks.size
      };
    }

    if (kind === "interview") {
      const empId = String(evt.employee || args.employee || data.employee || "");
      const topic = String(evt.topic || args.topic || data.topic || "recent_documents");
      let targetRoom = "Security Desk";
      if (
        evt.room === "Meeting Room A" ||
        evt.room === "Meeting Room B" ||
        evt.room === "Security Desk"
      ) {
        targetRoom = evt.room;
      } else if (topic === "recent_documents") {
        targetRoom = "Meeting Room A";
      } else if (topic === "workload") {
        targetRoom = "Meeting Room B";
      }
      const roomPts = this.map.waypoints[targetRoom] || this.map.waypoints["Security Desk"];
      const empSpot = roomPts[0];
      const invSpot = roomPts[1] || { x: empSpot.x, y: empSpot.y + 1 };
      const actor = this.actors.get(empId);
      if (actor) {
        this._moveActorTo(actor, empSpot.x, empSpot.y, "interview");
        actor.dwellMs = 3400;
      }
      this.investigator.path = findWalkPath(
        this.map,
        { x: this.investigator.x, y: this.investigator.y },
        invSpot
      ).slice(1);
      this.activeInterview = {
        employeeId: empId,
        topic,
        room: targetRoom,
        x: empSpot.x,
        y: empSpot.y,
        timerMs: 3400
      };
      this.setClock({ actionsUsed: this.clock.actionsUsed + 1 });
      return { handled: true, kind, employeeId: empId, room: targetRoom };
    }

    if (kind === "restrict_access") {
      const empId = String(data.restricted || evt.employee || args.employee || "");
      if (empId) {
        this.restrictedIds.add(empId);
        const actor = this.actors.get(empId);
        if (actor) {
          this._moveActorTo(actor, actor.homeX, actor.homeY, "restricted");
        }
      }
      this.setClock({ actionsUsed: this.clock.actionsUsed + 1 });
      return { handled: true, kind, employeeId: empId, restricted: true };
    }

    if (kind === "unrestrict_access") {
      const empId = String(data.unrestricted || evt.employee || args.employee || "");
      if (empId) {
        this.restrictedIds.delete(empId);
        const actor = this.actors.get(empId);
        if (actor) {
          actor.state = "desk";
        }
      }
      this.setClock({ actionsUsed: this.clock.actionsUsed + 1 });
      return { handled: true, kind, employeeId: empId, restricted: false };
    }

    if (kind === "read_access_logs") {
      const logs = Array.isArray(evt.logs) ? evt.logs : Array.isArray(data.logs) ? data.logs : [];
      const dayFrom = Number(evt.day_from ?? args.day_from ?? 1);
      const dayTo = Number(evt.day_to ?? args.day_to ?? this.clock.day);
      const flagged = new Set();
      for (let i = 0; i < logs.length; i += 1) {
        const row = logs[i] || {};
        const rowDay = row.day !== undefined ? Number(row.day) : dayFrom;
        if (row.after_hours === true && rowDay >= dayFrom && rowDay <= dayTo && row.employee) {
          const empId = String(row.employee);
          flagged.add(empId);
          const prev = this.afterHoursMarks.get(empId) || { count: 0, days: [] };
          const days = prev.days.includes(rowDay) ? prev.days : [...prev.days, rowDay];
          this.afterHoursMarks.set(empId, { count: prev.count + 1, days, timerMs: 5000 });
        }
      }
      const srvPts = this.map.waypoints["Server Room"];
      let idx = 0;
      for (const empId of flagged) {
        const actor = this.actors.get(empId);
        if (actor && !this.restrictedIds.has(empId) && idx < srvPts.length) {
          const pt = srvPts[idx];
          this._moveActorTo(actor, pt.x, pt.y, "server_log");
          actor.dwellMs = 2800;
          idx += 1;
        }
      }
      this.serverAlertTimerMs = flagged.size > 0 ? 4200 : 1200;
      this.setClock({ actionsUsed: this.clock.actionsUsed + 1 });
      return { handled: true, kind, afterHoursEmployees: Array.from(flagged) };
    }

    if (kind === "social_rumour" || kind === "social_rumor" || kind === "social_grudge") {
      const pair = Array.isArray(evt.employees) ? evt.employees : [];
      const empA = String(evt.from || evt.source || evt.actor || evt.employeeA || pair[0] || "");
      const empB = String(evt.to || evt.target || evt.subject || evt.employeeB || pair[1] || "");
      const coffeePts = this.map.waypoints["Coffee Corner"];
      const spotA = coffeePts[0];
      const spotB = coffeePts[1];
      const actorA = this.actors.get(empA);
      const actorB = this.actors.get(empB);
      if (actorA && !this.restrictedIds.has(empA)) {
        this._moveActorTo(actorA, spotA.x, spotA.y, "social");
        actorA.dwellMs = 3600;
      }
      if (actorB && !this.restrictedIds.has(empB)) {
        this._moveActorTo(actorB, spotB.x, spotB.y, "social");
        actorB.dwellMs = 3600;
      }
      const flavor = kind === "social_grudge" ? "grudge" : "rumour";
      this.socialInteractions.push({
        flavor,
        empA,
        empB,
        x: (spotA.x + spotB.x) * 0.5,
        y: Math.min(spotA.y, spotB.y),
        timerMs: 3800
      });
      return { handled: true, kind, flavor, employees: [empA, empB] };
    }

    if (kind === "advance_day") {
      const nextDay = data.day !== undefined ? Number(data.day) : this.clock.day + 1;
      const nextV = data.V !== undefined ? Number(data.V) : this.clock.V;
      this.overnightPulse = 1.0;
      this.setClock({ day: nextDay, actionsUsed: 0, V: nextV });
      if (data.episode_over === true || evt.done === true) {
        this.episodeDone = true;
      }
      return { handled: true, kind, day: this.clock.day, episodeDone: this.episodeDone };
    }

    if (kind === "status") {
      if (Array.isArray(data.restricted)) {
        this.restrictedIds = new Set(data.restricted.map((id) => String(id)));
      }
      const left = data.actions_left_today;
      const used =
        left !== undefined
          ? Math.max(0, this.clock.perDay - Number(left))
          : this.clock.actionsUsed;
      this.setClock({
        day: data.day !== undefined ? Number(data.day) : this.clock.day,
        V: data.V !== undefined ? Number(data.V) : this.clock.V,
        actionsUsed: used
      });
      return { handled: true, kind, phase: this.clock.phase };
    }

    if (kind === "accuse") {
      const accused = String(data.accused || evt.employee || args.employee || "");
      this.accusedId = accused || null;
      if (data.episode_over === true || evt.done !== false) {
        this.episodeDone = true;
      }
      return { handled: true, kind, accusedId: this.accusedId, episodeDone: this.episodeDone };
    }

    if (kind === "episode_over" || kind === "episode_done") {
      this.episodeDone = true;
      return { handled: true, kind, episodeDone: true };
    }

    return { handled: false, kind };
  }

  revealOutcome(outcome) {
    if (!this.episodeDone) {
      throw new Error("OfficeStage integrity gate: revealOutcome requires episodeDone === true");
    }
    if (!outcome || typeof outcome !== "object" || !outcome.moleId) {
      throw new Error("revealOutcome requires { moleId, accusedId, correct }");
    }
    const moleId = String(outcome.moleId);
    const accusedId = outcome.accusedId ? String(outcome.accusedId) : this.accusedId;
    const correct = Boolean(outcome.correct);
    const moleActor = this.actors.get(moleId);
    if (moleActor) {
      this._moveActorTo(moleActor, moleActor.homeX, moleActor.homeY, "mole_reveal");
    }
    this.revealedOutcome = {
      moleId,
      accusedId: accusedId || null,
      correct,
      pulseMs: 0
    };
    return { ...this.revealedOutcome };
  }

  setHumanMole(info) {
    if (this.mode !== "mole") {
      throw new Error('OfficeStage integrity gate: setHumanMole requires mode === "mole"');
    }
    if (!info || typeof info !== "object" || !info.employeeId) {
      throw new Error("setHumanMole requires { employeeId, leakedDocIds }");
    }
    const employeeId = String(info.employeeId);
    const leakedDocIds = Array.isArray(info.leakedDocIds)
      ? info.leakedDocIds.map((d) => String(d))
      : [];
    const moleActor = this.actors.get(employeeId);
    if (moleActor) {
      this._moveActorTo(moleActor, moleActor.homeX, moleActor.homeY, "human_mole");
    }
    this.humanMole = {
      employeeId,
      leakedDocIds,
      pulseMs: 0
    };
    return { ...this.humanMole };
  }

  _advancePathEntity(entity, dtSec, speedTiles) {
    if (!entity.path || entity.path.length === 0) {
      return false;
    }
    let remaining = dtSec * speedTiles;
    while (remaining > 0 && entity.path.length > 0) {
      const target = entity.path[0];
      const dx = target.x - entity.x;
      const dy = target.y - entity.y;
      const dist = Math.hypot(dx, dy);
      if (dist <= remaining || dist < 1e-4) {
        entity.x = target.x;
        entity.y = target.y;
        entity.path.shift();
        remaining -= dist;
      } else {
        entity.x += (dx / dist) * remaining;
        entity.y += (dy / dist) * remaining;
        remaining = 0;
      }
    }
    return true;
  }

  step(dtMs = 16.67) {
    const clampedMs = Math.max(0, Math.min(250, Number(dtMs) || 0));
    const dtSec = clampedMs / 1000;
    this.timeMs += clampedMs;

    if (this.overnightPulse > 0) {
      this.overnightPulse = Math.max(0, this.overnightPulse - dtSec * 0.9);
    }
    if (this.leakBanner.active) {
      this.leakBanner.timerMs = Math.max(0, this.leakBanner.timerMs - clampedMs);
      if (this.leakBanner.timerMs === 0) {
        this.leakBanner.active = false;
      }
    }
    if (this.serverAlertTimerMs > 0) {
      this.serverAlertTimerMs = Math.max(0, this.serverAlertTimerMs - clampedMs);
    }
    if (this.activeInterview) {
      this.activeInterview.timerMs = Math.max(0, this.activeInterview.timerMs - clampedMs);
      if (this.activeInterview.timerMs === 0) {
        const targetActor = this.actors.get(this.activeInterview.employeeId);
        if (targetActor && !this.restrictedIds.has(targetActor.id)) {
          this._moveActorTo(targetActor, targetActor.homeX, targetActor.homeY, "desk");
        }
        this.activeInterview = null;
      }
    }
    for (let i = this.socialInteractions.length - 1; i >= 0; i -= 1) {
      this.socialInteractions[i].timerMs -= clampedMs;
      if (this.socialInteractions[i].timerMs <= 0) {
        const item = this.socialInteractions[i];
        const a = this.actors.get(item.empA);
        const b = this.actors.get(item.empB);
        if (a && !this.restrictedIds.has(a.id)) {
          this._moveActorTo(a, a.homeX, a.homeY, "desk");
        }
        if (b && !this.restrictedIds.has(b.id)) {
          this._moveActorTo(b, b.homeX, b.homeY, "desk");
        }
        this.socialInteractions.splice(i, 1);
      }
    }
    for (const [empId, mark] of this.afterHoursMarks.entries()) {
      mark.timerMs = Math.max(0, mark.timerMs - clampedMs);
      if (mark.timerMs === 0 && mark.count === 0) {
        this.afterHoursMarks.delete(empId);
      }
    }
    if (this.revealedOutcome) {
      this.revealedOutcome.pulseMs += clampedMs;
    }
    if (this.humanMole) {
      this.humanMole.pulseMs += clampedMs;
    }

    this._advancePathEntity(this.investigator, dtSec, this.investigator.speedTilesPerSec);

    const facilityTargets = [
      "Coffee Corner",
      "Meeting Room A",
      "Meeting Room B",
      "Server Room"
    ];
    for (const actor of this.actors.values()) {
      const moving = this._advancePathEntity(actor, dtSec, 4.8);
      if (moving) {
        actor.walkPhase = (actor.walkPhase + dtSec * 9.0) % (Math.PI * 2);
        continue;
      }
      actor.walkPhase = 0;
      if (this.restrictedIds.has(actor.id)) {
        continue;
      }
      if (
        (this.revealedOutcome && this.revealedOutcome.moleId === actor.id) ||
        (this.humanMole && this.humanMole.employeeId === actor.id)
      ) {
        continue;
      }
      actor.dwellMs -= clampedMs;
      if (actor.dwellMs <= 0) {
        this.strollTick += 1;
        const atHome =
          Math.abs(actor.x - actor.homeX) < 0.1 && Math.abs(actor.y - actor.homeY) < 0.1;
        const h = hashString(`${actor.id}:${this.clock.day}:${this.strollTick}`);
        if (!atHome) {
          this._moveActorTo(actor, actor.homeX, actor.homeY, "desk");
          actor.dwellMs = 2600 + (h % 3400);
        } else if (h % 5 === 0) {
          const roomName = facilityTargets[(h >>> 4) % facilityTargets.length];
          const pts = this.map.waypoints[roomName];
          const pt = pts[(h >>> 8) % pts.length];
          this._moveActorTo(actor, pt.x, pt.y, "stroll");
          actor.dwellMs = 1800 + (h % 2000);
        } else {
          actor.dwellMs = 2200 + (h % 2600);
        }
      }
    }
    return this;
  }

  _drawSpriteOrFallback(sheetImg, spriteKey, px, py, fallbackFn) {
    const pack = this.spritePack;
    if (
      pack &&
      pack.loaded &&
      sheetImg &&
      !sheetImg.headless &&
      pack.sprites &&
      pack.sprites[spriteKey] &&
      typeof this.ctx.drawImage === "function"
    ) {
      const sp = pack.sprites[spriteKey];
      const sx = Number(sp.x) || 0;
      const sy = Number(sp.y) || 0;
      const sw = Number(sp.w) || pack.frameW;
      const sh = Number(sp.h) || pack.frameH;
      this.ctx.drawImage(sheetImg, sx, sy, sw, sh, px, py, TILE_SIZE, TILE_SIZE);
      return;
    }
    fallbackFn();
  }

  _renderSkyStrip(ctx) {
    const phase = this.clock.phase;
    let skyTop = "rgb(86, 168, 242)";
    let skyBot = "rgb(152, 208, 250)";
    if (phase === "morning") {
      skyTop = "rgb(98, 162, 228)";
      skyBot = "rgb(244, 198, 122)";
    } else if (phase === "dusk") {
      skyTop = "rgb(96, 68, 148)";
      skyBot = "rgb(232, 122, 92)";
    } else if (phase === "night") {
      skyTop = "rgb(14, 22, 46)";
      skyBot = "rgb(28, 40, 74)";
    }

    ctx.fillStyle = "rgb(16, 22, 32)";
    ctx.fillRect(0, 0, this.logicalWidth, TILE_SIZE);

    for (let x = 1; x < GRID_COLS - 1; x += 1) {
      const px = x * TILE_SIZE;
      const py = TILE_SIZE;
      ctx.fillStyle = skyTop;
      ctx.fillRect(px + 1, py + 2, TILE_SIZE - 2, 6);
      ctx.fillStyle = skyBot;
      ctx.fillRect(px + 1, py + 8, TILE_SIZE - 2, 6);
      ctx.fillStyle = "rgb(38, 48, 64)";
      ctx.fillRect(px, py, TILE_SIZE, 2);
      ctx.fillRect(px, py + 14, TILE_SIZE, 2);
      ctx.fillRect(px, py, 1, TILE_SIZE);
      if (phase === "night" && (x * 7 + this.clock.day) % 5 === 0) {
        ctx.fillStyle = "rgb(238, 244, 255)";
        ctx.fillRect(px + 5, py + 4, 2, 2);
      }
    }
  }

  _renderFloorAndZones(ctx) {
    for (let y = 2; y < GRID_ROWS; y += 1) {
      for (let x = 0; x < GRID_COLS; x += 1) {
        const px = x * TILE_SIZE;
        const py = y * TILE_SIZE;
        const cell = this.map.grid[y][x];
        if (cell === "wall") {
          ctx.fillStyle = "rgb(20, 26, 36)";
          ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
        } else if (cell === "corridor" || cell === "door") {
          ctx.fillStyle = (x + y) % 2 === 0 ? "rgb(34, 42, 54)" : "rgb(38, 46, 59)";
          ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
        } else {
          ctx.fillStyle = "rgb(28, 36, 48)";
          ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
        }
      }
    }

    for (let i = 0; i < ZONE_LIST.length; i += 1) {
      const z = ZONE_LIST[i];
      for (let y = z.y; y < z.y + z.h; y += 1) {
        for (let x = z.x; x < z.x + z.w; x += 1) {
          const cell = this.map.grid[y][x];
          const px = x * TILE_SIZE;
          const py = y * TILE_SIZE;
          if (cell === "partition") {
            ctx.fillStyle = "rgb(52, 64, 82)";
            ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
            ctx.fillStyle = z.accent;
            ctx.fillRect(px + 2, py + 6, TILE_SIZE - 4, 2);
          } else {
            ctx.fillStyle = (x + y) % 2 === 0 ? z.floorA : z.floorB;
            ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
          }
        }
      }
      if (typeof ctx.fillText === "function") {
        ctx.fillStyle = z.accent;
        ctx.font = "bold 7px monospace";
        ctx.fillText(z.name.toUpperCase(), (z.x + 0.4) * TILE_SIZE, (z.y + 0.75) * TILE_SIZE);
      }
    }
  }

  _renderFacilityFurniture(ctx) {
    for (let y = 2; y < GRID_ROWS - 1; y += 1) {
      for (let x = 1; x < GRID_COLS - 1; x += 1) {
        const cell = this.map.grid[y][x];
        const px = x * TILE_SIZE;
        const py = y * TILE_SIZE;
        if (cell === "coffee_bar") {
          ctx.fillStyle = "rgb(112, 74, 46)";
          ctx.fillRect(px + 1, py + 2, 14, 12);
          ctx.fillStyle = "rgb(214, 222, 232)";
          ctx.fillRect(px + 4, py + 4, 6, 6);
        } else if (cell === "bistro_table") {
          ctx.fillStyle = "rgb(146, 104, 68)";
          ctx.fillRect(px + 3, py + 3, 10, 10);
        } else if (cell === "meeting_table") {
          ctx.fillStyle = "rgb(74, 96, 122)";
          ctx.fillRect(px, py + 2, TILE_SIZE, 12);
        } else if (cell === "security_console") {
          ctx.fillStyle = "rgb(48, 56, 72)";
          ctx.fillRect(px, py + 2, TILE_SIZE, 12);
          ctx.fillStyle = "rgb(232, 94, 94)";
          ctx.fillRect(px + 3, py + 4, 10, 4);
        } else if (cell === "server_rack") {
          ctx.fillStyle = "rgb(24, 32, 42)";
          ctx.fillRect(px + 2, py + 1, 12, 14);
          const blinkOn = Math.floor(this.timeMs / 260 + y) % 2 === 0;
          ctx.fillStyle =
            this.serverAlertTimerMs > 0
              ? "rgb(246, 178, 58)"
              : blinkOn
                ? "rgb(72, 224, 146)"
                : "rgb(42, 124, 92)";
          ctx.fillRect(px + 4, py + 4, 3, 2);
          ctx.fillRect(px + 9, py + 8, 3, 2);
        }
      }
    }
  }

  _renderDesks(ctx) {
    const pulse = 0.5 + 0.5 * Math.sin(this.timeMs * 0.008);
    for (let i = 0; i < this.map.desks.length; i += 1) {
      const d = this.map.desks[i];
      const px = d.x * TILE_SIZE;
      const py = d.y * TILE_SIZE;
      const empId = d.employeeId;

      this._drawSpriteOrFallback(
        this.spritePack ? this.spritePack.tileImage : null,
        "desk",
        px,
        py,
        () => {
          ctx.fillStyle = "rgb(82, 94, 114)";
          ctx.fillRect(px + 1, py + 2, 14, 11);
          ctx.fillStyle = empId ? "rgb(98, 192, 246)" : "rgb(46, 58, 72)";
          ctx.fillRect(px + 4, py + 3, 8, 5);
          ctx.fillStyle = "rgb(54, 64, 80)";
          ctx.fillRect(px + 4, py + 16, 8, 5);
        }
      );

      if (!empId) {
        continue;
      }

      if (this.highlightedVariantDesks.has(empId)) {
        ctx.strokeStyle = `rgba(248, 78, 92, ${(0.55 + 0.4 * pulse).toFixed(2)})`;
        ctx.lineWidth = 2;
        ctx.strokeRect(px - 1, py - 1, TILE_SIZE + 2, TILE_SIZE * 2 + 2);
      }

      const canary = this.deskCanaries.get(empId);
      if (canary) {
        const pal = VARIANT_PALETTE[canary.variant] || VARIANT_PALETTE.A;
        ctx.fillStyle = pal.fill;
        ctx.fillRect(px + 9, py + 6, 6, 6);
        if (typeof ctx.fillText === "function") {
          ctx.fillStyle = pal.ink;
          ctx.font = "bold 6px monospace";
          ctx.fillText(canary.variant.slice(0, 1), px + 10, py + 11);
        }
      }

      if (this.restrictedIds.has(empId)) {
        ctx.strokeStyle = "rgb(246, 168, 52)";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(px, py, TILE_SIZE, TILE_SIZE * 2);
        ctx.fillStyle = "rgb(246, 168, 52)";
        ctx.fillRect(px + 1, py + 1, 5, 5);
      }

      if (this.afterHoursMarks.has(empId)) {
        ctx.fillStyle = "rgb(242, 118, 64)";
        ctx.fillRect(px + 1, py + 8, 6, 4);
      }

      const isRevealedMole =
        this.episodeDone &&
        this.revealedOutcome &&
        this.revealedOutcome.moleId === empId;
      const isHumanMole =
        this.mode === "mole" &&
        this.humanMole &&
        this.humanMole.employeeId === empId;

      if (isRevealedMole || isHumanMole) {
        ctx.strokeStyle = "rgb(252, 62, 82)";
        ctx.lineWidth = 2;
        ctx.strokeRect(px - 2, py - 2, TILE_SIZE + 4, TILE_SIZE * 2 + 4);
        const rise = Math.floor((this.timeMs * 0.02) % 8);
        ctx.fillStyle = "rgb(252, 78, 96)";
        ctx.fillRect(px + 5, py - 2 - rise, 6, 4);
      }
    }
  }

  _renderActors(ctx) {
    for (const actor of this.actors.values()) {
      const px = Math.round(actor.x * TILE_SIZE);
      const py = Math.round(actor.y * TILE_SIZE);
      const stepBob = actor.walkPhase > 0 ? Math.round(Math.sin(actor.walkPhase) * 1) : 0;

      this._drawSpriteOrFallback(
        this.spritePack ? this.spritePack.charImage : null,
        "employee",
        px,
        py,
        () => {
          ctx.fillStyle = "rgba(0, 0, 0, 0.35)";
          ctx.fillRect(px + 4, py + 13, 8, 2);
          ctx.fillStyle = "rgb(36, 44, 58)";
          ctx.fillRect(px + 5, py + 11 + stepBob, 2, 3);
          ctx.fillRect(px + 9, py + 11 - stepBob, 2, 3);
          ctx.fillStyle = actor.jacket;
          ctx.fillRect(px + 4, py + 7, 8, 5);
          ctx.fillStyle = "rgb(242, 246, 252)";
          for (let b = 0; b < actor.badgePips; b += 1) {
            ctx.fillRect(px + 5 + b * 2, py + 8, 1, 1);
          }
          ctx.fillStyle = actor.skin;
          ctx.fillRect(px + 5, py + 3, 6, 4);
          ctx.fillStyle = actor.hair;
          ctx.fillRect(px + 5, py + 2, 6, 2);
          if (actor.hairStyle === 1) {
            ctx.fillRect(px + 4, py + 3, 1, 2);
          } else if (actor.hairStyle === 2) {
            ctx.fillRect(px + 11, py + 3, 1, 2);
          } else if (actor.hairStyle === 3) {
            ctx.fillRect(px + 6, py + 1, 4, 1);
          }
        }
      );

      if (this.accusedId === actor.id) {
        ctx.strokeStyle = "rgb(250, 214, 72)";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(px + 1, py + 1, TILE_SIZE - 2, TILE_SIZE - 2);
      }
    }

    const ipx = Math.round(this.investigator.x * TILE_SIZE);
    const ipy = Math.round(this.investigator.y * TILE_SIZE);
    ctx.fillStyle = "rgb(238, 242, 248)";
    ctx.fillRect(ipx + 4, ipy + 6, 8, 6);
    ctx.fillStyle = "rgb(232, 94, 94)";
    ctx.fillRect(ipx + 5, ipy + 2, 6, 4);
  }

  _renderOverlays(ctx) {
    if (this.activeInterview) {
      const bx = this.activeInterview.x * TILE_SIZE;
      const by = (this.activeInterview.y - 1) * TILE_SIZE;
      ctx.fillStyle = "rgb(244, 248, 255)";
      ctx.fillRect(bx + 2, by + 4, 12, 8);
      ctx.fillStyle = "rgb(32, 46, 68)";
      ctx.fillRect(bx + 4, by + 7, 2, 2);
      ctx.fillRect(bx + 7, by + 7, 2, 2);
      ctx.fillRect(bx + 10, by + 7, 2, 2);
    }

    for (let i = 0; i < this.socialInteractions.length; i += 1) {
      const item = this.socialInteractions[i];
      const sx = Math.round(item.x * TILE_SIZE);
      const sy = Math.round((item.y - 0.8) * TILE_SIZE);
      if (item.flavor === "grudge") {
        ctx.fillStyle = "rgb(248, 92, 68)";
        ctx.fillRect(sx + 4, sy + 3, 8, 8);
      } else {
        ctx.fillStyle = "rgb(122, 218, 248)";
        ctx.fillRect(sx + 3, sy + 4, 10, 7);
      }
    }

    const phase = this.clock.phase;
    if (phase === "morning") {
      ctx.fillStyle = "rgba(255, 214, 150, 0.06)";
      ctx.fillRect(0, TILE_SIZE * 2, this.logicalWidth, this.logicalHeight - TILE_SIZE * 2);
    } else if (phase === "dusk") {
      ctx.fillStyle = "rgba(176, 96, 148, 0.14)";
      ctx.fillRect(0, TILE_SIZE * 2, this.logicalWidth, this.logicalHeight - TILE_SIZE * 2);
    } else if (phase === "night") {
      ctx.fillStyle = "rgba(14, 22, 54, 0.28)";
      ctx.fillRect(0, TILE_SIZE * 2, this.logicalWidth, this.logicalHeight - TILE_SIZE * 2);
    }

    if (this.overnightPulse > 0) {
      const alpha = (this.overnightPulse * 0.45).toFixed(3);
      ctx.fillStyle = `rgba(10, 16, 36, ${alpha})`;
      ctx.fillRect(0, 0, this.logicalWidth, this.logicalHeight);
    }

    if (this.leakBanner.active) {
      ctx.fillStyle = "rgba(214, 42, 62, 0.9)";
      ctx.fillRect(0, 0, this.logicalWidth, TILE_SIZE);
      if (typeof ctx.fillText === "function") {
        ctx.fillStyle = "rgb(255, 246, 246)";
        ctx.font = "bold 9px monospace";
        ctx.fillText(
          `LEAK FEED ALERT (${this.leakBanner.count}) ${this.leakBanner.lastLabel}`,
          8,
          11
        );
      }
    } else if (typeof ctx.fillText === "function") {
      ctx.fillStyle = "rgb(206, 218, 234)";
      ctx.font = "8px monospace";
      ctx.fillText(
        `DAY ${this.clock.day}/${this.clock.nDays}  PHASE:${this.clock.phase.toUpperCase()}  V:${this.clock.V.toFixed(2)}`,
        8,
        11
      );
    }
  }

  render() {
    const rawCtx = this.ctx;
    if (!rawCtx) {
      return { frameCount: this.frameCount, phase: this.clock.phase };
    }
    const ctx =
      typeof rawCtx.fillRect === "function" && typeof rawCtx.strokeRect === "function"
        ? rawCtx
        : Object.assign(createHeadlessContext(), rawCtx);
    if (typeof ctx.save === "function") {
      ctx.save();
    }
    ctx.imageSmoothingEnabled = false;
    if (
      this.canvas &&
      Number(this.canvas.width) > 0 &&
      Number(this.canvas.height) > 0 &&
      (this.canvas.width !== this.logicalWidth || this.canvas.height !== this.logicalHeight) &&
      typeof ctx.scale === "function"
    ) {
      ctx.scale(
        this.canvas.width / this.logicalWidth,
        this.canvas.height / this.logicalHeight
      );
    }
    if (typeof ctx.clearRect === "function") {
      ctx.clearRect(0, 0, this.logicalWidth, this.logicalHeight);
    }

    this._renderSkyStrip(ctx);
    this._renderFloorAndZones(ctx);
    this._renderFacilityFurniture(ctx);
    this._renderDesks(ctx);
    this._renderActors(ctx);
    this._renderOverlays(ctx);

    if (typeof ctx.restore === "function") {
      ctx.restore();
    }
    this.frameCount += 1;
    return {
      frameCount: this.frameCount,
      phase: this.clock.phase,
      zoneCount: ZONE_LIST.length,
      employeeCount: this.actors.size,
      restrictedCount: this.restrictedIds.size,
      episodeDone: this.episodeDone
    };
  }

  start() {
    if (this._destroyed || this._running) {
      return this;
    }
    this._running = true;
    const nowFn = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
    this._lastNow = nowFn();

    const tick = (ts) => {
      if (!this._running || this._destroyed) {
        return;
      }
      const cur = typeof ts === "number" ? ts : nowFn();
      const dt = Math.max(0, cur - this._lastNow);
      this._lastNow = cur;
      this.step(dt || 16.67);
      this.render();
      if (typeof requestAnimationFrame === "function") {
        this._rafId = requestAnimationFrame(tick);
      }
    };

    if (typeof requestAnimationFrame === "function") {
      this._rafId = requestAnimationFrame(tick);
    } else if (typeof setInterval === "function") {
      this._timerId = setInterval(() => {
        if (!this._running || this._destroyed) {
          return;
        }
        this.step(16.67);
        this.render();
      }, 16);
    }
    return this;
  }

  stop() {
    this._running = false;
    if (this._rafId !== null && typeof cancelAnimationFrame === "function") {
      cancelAnimationFrame(this._rafId);
    }
    this._rafId = null;
    if (this._timerId !== null && typeof clearInterval === "function") {
      clearInterval(this._timerId);
    }
    this._timerId = null;
    return this;
  }

  destroy() {
    this.stop();
    this._destroyed = true;
    this.actors.clear();
  }
}

export async function loadSpritePack(stageOrManifest, maybeManifest) {
  if (stageOrManifest instanceof OfficeStage) {
    return stageOrManifest.loadSpritePack(maybeManifest);
  }
  const pack = await resolveSpritePackManifest(stageOrManifest);
  sharedSpritePack = pack;
  return pack;
}

export function getCreditsText(stage) {
  if (stage instanceof OfficeStage) {
    return stage.getCreditsText();
  }
  return sharedSpritePack && sharedSpritePack.creditsText
    ? sharedSpritePack.creditsText
    : DEFAULT_CREDITS;
}

export function setClock(stage, clock) {
  if (!(stage instanceof OfficeStage)) {
    throw new Error("setClock requires an OfficeStage instance");
  }
  return stage.setClock(clock);
}

export function applyObservableEvent(stage, evt) {
  if (!(stage instanceof OfficeStage)) {
    throw new Error("applyObservableEvent requires an OfficeStage instance");
  }
  return stage.applyObservableEvent(evt);
}

export function revealOutcome(stage, outcome) {
  if (!(stage instanceof OfficeStage)) {
    throw new Error("revealOutcome requires an OfficeStage instance");
  }
  return stage.revealOutcome(outcome);
}

export function setHumanMole(stage, info) {
  if (!(stage instanceof OfficeStage)) {
    throw new Error("setHumanMole requires an OfficeStage instance");
  }
  return stage.setHumanMole(info);
}
