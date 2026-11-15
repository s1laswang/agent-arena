# Canary Arena: 40-Employee Sprite Cast and 40x24 Office Map

Deterministic CC0 sprite manifest and spatial floorplan for `OfficeStage.loadSpritePack(manifest)` in Canary Arena (`docs/arena/data/sprite_manifest_40emp.json` and offline `docs/arena/data/sprite_manifest_40emp.js`).

## 1. Architecture and Public-Only Integrity Contract

- **Schema**: `canary.arena.sprite_manifest_40emp.v1` (Canary tiers `v1.4`)
- **Stage Geometry**: `40x24` tiles at `16px` (`640x384` pixels)
- **Walkable Connectivity**: `559/559` walkable tiles 4-directionally connected from hub `[20, 10]`
- **Tier Coverage**: `hard` (`e00..e39`, 40 staff, 5 departments, 21 days), `medium` (`e00..e19`, 20 staff, 4 departments, 14 days), and `easy` (`e00..e11`, 12 staff, 4 departments, 14 days)
- **Public-Only Determinism**: Every sprite coordinate, desk seat, badge pip count, palette tint, and silhouette glyph is derived strictly from public employee fields (`id`, `dept`, `role`). Zero private state is ever read or stored.

## 2. Office Floorplan (`40x24` Grid)

```text
00 WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
01 W======================================W
02 W,,,,,,,,,,,|.|,,,,,,,,,,|.|,,,,,,,,,,,W
03 W,D,,D,,D,,D|.|D,,D,,D,,D|.|D,,D,,D,,D,W
04 W,C,,C,,C,,C|.|C,,C,,C,,C|.|C,,C,,C,,C,W
05 W,,,,,,,,,,,+.+,,,,,,,,,,+.+,,,,,,,,,,,W
06 W,D,,D,,D,,D|.|D,,D,,D,,D|.|D,,D,,D,,D,W
07 W,C,,C,,C,,C|.|C,,C,,C,,C|.|C,,C,,C,,C,W
08 W||||++||||||.|||||++|||||.|||||++|||||W
09 W......................................W
10 W......................................W
11 W|||||++|||||.|||||++|||||.|||||++|||||W
12 W,D,,D,,D,,D|.|D,,D,,D,,D|.|,,,,,,KKKK,W
13 W,C,,C,,C,,C+.+C,,C,,C,,C+.+,B,,,,,,,,,W
14 W,D,,D,,D,,D|.|D,,D,,D,,D|.+,,,,,,B,,,,W
15 W,C,,C,,C,,C|.|C,,C,,C,,C|.|,,,,,,,,,,,W
16 W|||||++|||||.|||||++|||||.|||||++|||||W
17 W......................................W
18 W|||++||||.|||++||||.|||++||||.|||++|||W
19 W,,,,,,,,|.|,,,,,,,|.|,,,,,,,|.|R,,,,R,W
20 W,,TTTT,,|.|,TTTT,,|.|P,SSS,A|.|R,,,,R,W
21 W,,,,,,,,|.|,,,,,,,|.|,,,,,,,|.|R,,,,R,W
22 W,,,,,,,,|L|,,,,,,,|.|,,,,,,,|L|,,,,,,,W
23 WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW
```

### Tile Legend

| Symbol | Tile Name | Walkable | Sheet | `(col, row)` | Fallback RGB |
| :---: | :--- | :---: | :--- | :---: | :--- |
| `W` | `perimeter_wall` | `no` | `indoors` | `(1, 0)` | `rgb(20, 26, 36)` |
| `=` | `exterior_window` | `no` | `indoors` | `(5, 0)` | `rgb(86, 168, 242)` |
| `|` | `glass_partition` | `no` | `indoors` | `(5, 1)` | `rgb(52, 64, 82)` |
| `+` | `doorway_threshold` | `yes` | `indoors` | `(3, 2)` | `rgb(38, 46, 59)` |
| `.` | `corridor_floor` | `yes` | `indoors` | `(0, 3)` | `rgb(34, 42, 54)` |
| `,` | `zone_floor` | `yes` | `indoors` | `(1, 3)` | `rgb(28, 36, 48)` |
| `C` | `task_chair` | `yes` | `indoors` | `(18, 0)` | `rgb(54, 64, 80)` |
| `D` | `workstation_desk` | `no` | `indoors` | `(8, 0)` | `rgb(82, 94, 114)` |
| `T` | `meeting_table` | `no` | `indoors` | `(12, 0)` | `rgb(74, 96, 122)` |
| `B` | `bistro_table` | `no` | `indoors` | `(13, 0)` | `rgb(146, 104, 68)` |
| `K` | `coffee_bar` | `no` | `indoors` | `(9, 0)` | `rgb(112, 74, 46)` |
| `S` | `security_console` | `no` | `indoors` | `(15, 0)` | `rgb(48, 56, 72)` |
| `P` | `canary_printer` | `no` | `indoors` | `(17, 0)` | `rgb(246, 192, 68)` |
| `A` | `doc_archive` | `no` | `indoors` | `(11, 0)` | `rgb(148, 163, 184)` |
| `R` | `server_rack` | `no` | `indoors` | `(14, 0)` | `rgb(24, 32, 42)` |
| `L` | `leak_drop_relay` | `no` | `indoors` | `(21, 0)` | `rgb(232, 94, 94)` |

### Zones and Investigation Facilities

| Zone Name | Kind | Bounds `(x, y, w, h)` | Accent RGB |
| :--- | :---: | :---: | :--- |
| Engineering | `department` | `(1, 2, 12, 7)` | `rgb(56, 152, 236)` |
| Research | `department` | `(14, 2, 12, 7)` | `rgb(46, 196, 198)` |
| Finance | `department` | `(27, 2, 12, 7)` | `rgb(52, 188, 122)` |
| Sales | `department` | `(1, 11, 12, 6)` | `rgb(238, 146, 54)` |
| Legal | `department` | `(14, 11, 12, 6)` | `rgb(166, 110, 228)` |
| Coffee Corner | `facility` | `(27, 11, 12, 6)` | `rgb(218, 162, 92)` |
| Meeting Room A | `facility` | `(1, 18, 9, 5)` | `rgb(102, 168, 224)` |
| Meeting Room B | `facility` | `(11, 18, 9, 5)` | `rgb(120, 184, 164)` |
| Security Desk | `facility` | `(21, 18, 9, 5)` | `rgb(232, 94, 94)` |
| Server Room | `facility` | `(31, 18, 8, 5)` | `rgb(72, 214, 152)` |
| Canary Printer | `station` | `(22, 20, 1, 1)` | `rgb(246, 192, 68)` |
| Doc Archive | `station` | `(28, 20, 1, 1)` | `rgb(148, 163, 184)` |
| Leak Drop Relay | `station` | `(10, 22, 21, 1)` | `rgb(232, 94, 94)` |

## 3. 40-Employee Animated Cast (`e00..e39`)

| ID | Dept | Role | Home Desk | Chair `(x, y)` | Char `(col, row)` | Hair / Outfit / Accessory | Shirt RGB |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| `e00` | Engineering | `engineer` | `desk_00` | `(2, 4)` | `(0, 1)` | `short_part` / `hoodie` / `lanyard` | `rgb(14, 165, 233)` |
| `e01` | Finance | `analyst` | `desk_08` | `(28, 4)` | `(1, 2)` | `bun` / `blazer` / `id_pin` | `rgb(16, 185, 129)` |
| `e02` | Sales | `account exec` | `desk_16` | `(2, 13)` | `(2, 3)` | `curly` / `vest` / `lanyard` | `rgb(249, 115, 22)` |
| `e03` | Legal | `counsel` | `desk_24` | `(15, 13)` | `(3, 4)` | `spiky` / `turtleneck` / `id_pin` | `rgb(139, 92, 246)` |
| `e04` | Research | `scientist` | `desk_32` | `(15, 4)` | `(4, 5)` | `bob` / `labcoat` / `lanyard` | `rgb(236, 72, 153)` |
| `e05` | Engineering | `senior engineer` | `desk_01` | `(5, 4)` | `(5, 6)` | `buzz` / `hoodie` / `clipboard_tab` | `rgb(2, 132, 199)` |
| `e06` | Finance | `controller` | `desk_09` | `(31, 4)` | `(6, 7)` | `ponytail` / `blazer` / `tie_clip` | `rgb(5, 150, 105)` |
| `e07` | Sales | `sales manager` | `desk_17` | `(5, 13)` | `(7, 8)` | `swept` / `vest` / `clipboard_tab` | `rgb(234, 88, 12)` |
| `e08` | Legal | `paralegal` | `desk_25` | `(18, 13)` | `(8, 9)` | `short_part` / `turtleneck` / `tie_clip` | `rgb(124, 58, 237)` |
| `e09` | Research | `research lead` | `desk_33` | `(18, 4)` | `(9, 10)` | `bun` / `labcoat` / `clipboard_tab` | `rgb(219, 39, 119)` |
| `e10` | Engineering | `tech lead` | `desk_02` | `(8, 4)` | `(12, 1)` | `curly` / `hoodie` / `scarf` | `rgb(56, 189, 248)` |
| `e11` | Finance | `accountant` | `desk_10` | `(34, 4)` | `(13, 2)` | `spiky` / `blazer` / `headset` | `rgb(52, 211, 153)` |
| `e12` | Sales | `sales ops` | `desk_18` | `(8, 13)` | `(14, 3)` | `bob` / `vest` / `scarf` | `rgb(251, 146, 60)` |
| `e13` | Legal | `compliance officer` | `desk_26` | `(21, 13)` | `(15, 4)` | `buzz` / `turtleneck` / `headset` | `rgb(167, 139, 250)` |
| `e14` | Research | `lab analyst` | `desk_34` | `(21, 4)` | `(16, 5)` | `ponytail` / `labcoat` / `scarf` | `rgb(244, 114, 182)` |
| `e15` | Engineering | `engineer` | `desk_03` | `(11, 4)` | `(17, 6)` | `swept` / `hoodie` / `wristwatch` | `rgb(37, 99, 235)` |
| `e16` | Finance | `analyst` | `desk_11` | `(37, 4)` | `(18, 7)` | `short_part` / `blazer` / `glasses` | `rgb(20, 184, 166)` |
| `e17` | Sales | `account exec` | `desk_19` | `(11, 13)` | `(19, 8)` | `bun` / `vest` / `wristwatch` | `rgb(245, 158, 11)` |
| `e18` | Legal | `counsel` | `desk_27` | `(24, 13)` | `(20, 9)` | `curly` / `turtleneck` / `glasses` | `rgb(99, 102, 241)` |
| `e19` | Research | `scientist` | `desk_35` | `(24, 4)` | `(21, 10)` | `spiky` / `labcoat` / `wristwatch` | `rgb(225, 29, 72)` |
| `e20` | Engineering | `senior engineer` | `desk_04` | `(2, 7)` | `(24, 1)` | `bob` / `hoodie` / `id_pin` | `rgb(29, 78, 216)` |
| `e21` | Finance | `controller` | `desk_12` | `(28, 7)` | `(25, 2)` | `buzz` / `blazer` / `lanyard` | `rgb(13, 148, 136)` |
| `e22` | Sales | `sales manager` | `desk_20` | `(2, 15)` | `(26, 3)` | `ponytail` / `vest` / `id_pin` | `rgb(217, 119, 6)` |
| `e23` | Legal | `paralegal` | `desk_28` | `(15, 15)` | `(27, 4)` | `swept` / `turtleneck` / `lanyard` | `rgb(79, 70, 229)` |
| `e24` | Research | `research lead` | `desk_36` | `(15, 7)` | `(28, 5)` | `short_part` / `labcoat` / `id_pin` | `rgb(190, 18, 60)` |
| `e25` | Engineering | `tech lead` | `desk_05` | `(5, 7)` | `(29, 6)` | `bun` / `hoodie` / `tie_clip` | `rgb(6, 182, 212)` |
| `e26` | Finance | `accountant` | `desk_13` | `(31, 7)` | `(30, 7)` | `curly` / `blazer` / `clipboard_tab` | `rgb(34, 197, 94)` |
| `e27` | Sales | `sales ops` | `desk_21` | `(5, 15)` | `(31, 8)` | `spiky` / `vest` / `tie_clip` | `rgb(239, 68, 68)` |
| `e28` | Legal | `compliance officer` | `desk_29` | `(18, 15)` | `(32, 9)` | `bob` / `turtleneck` / `clipboard_tab` | `rgb(147, 51, 234)` |
| `e29` | Research | `lab analyst` | `desk_37` | `(18, 7)` | `(33, 10)` | `buzz` / `labcoat` / `tie_clip` | `rgb(251, 113, 133)` |
| `e30` | Engineering | `engineer` | `desk_06` | `(8, 7)` | `(36, 1)` | `ponytail` / `hoodie` / `headset` | `rgb(8, 145, 178)` |
| `e31` | Finance | `analyst` | `desk_14` | `(34, 7)` | `(37, 2)` | `swept` / `blazer` / `scarf` | `rgb(22, 163, 74)` |
| `e32` | Sales | `account exec` | `desk_22` | `(8, 15)` | `(38, 3)` | `short_part` / `vest` / `headset` | `rgb(220, 38, 38)` |
| `e33` | Legal | `counsel` | `desk_30` | `(21, 15)` | `(39, 4)` | `bun` / `turtleneck` / `scarf` | `rgb(168, 85, 247)` |
| `e34` | Research | `scientist` | `desk_38` | `(21, 7)` | `(40, 5)` | `curly` / `labcoat` / `headset` | `rgb(244, 63, 94)` |
| `e35` | Engineering | `senior engineer` | `desk_07` | `(11, 7)` | `(41, 6)` | `spiky` / `hoodie` / `glasses` | `rgb(96, 165, 250)` |
| `e36` | Finance | `controller` | `desk_15` | `(37, 7)` | `(42, 7)` | `bob` / `blazer` / `wristwatch` | `rgb(74, 222, 128)` |
| `e37` | Sales | `sales manager` | `desk_23` | `(11, 15)` | `(43, 8)` | `buzz` / `vest` / `glasses` | `rgb(253, 186, 116)` |
| `e38` | Legal | `paralegal` | `desk_31` | `(24, 15)` | `(44, 9)` | `ponytail` / `turtleneck` / `wristwatch` | `rgb(192, 132, 252)` |
| `e39` | Research | `research lead` | `desk_39` | `(24, 7)` | `(45, 10)` | `swept` / `labcoat` / `glasses` | `rgb(253, 164, 175)` |

## 4. Day/Night Lighting Phases and 21-Day Nordic Campaign

| Phase | Action Ratio | Sky Top | Sky Bottom | Overlay RGBA |
| :--- | :---: | :--- | :--- | :--- |
| `morning` | `0.000..0.250` | `rgb(98, 162, 228)` | `rgb(244, 198, 122)` | `rgba(255, 214, 150, 0.06)` |
| `afternoon` | `0.250..0.625` | `rgb(86, 168, 242)` | `rgb(152, 208, 250)` | `rgba(255, 255, 255, 0.02)` |
| `dusk` | `0.625..0.875` | `rgb(96, 68, 148)` | `rgb(232, 122, 92)` | `rgba(176, 96, 148, 0.14)` |
| `night` | `0.875..1.000` | `rgb(14, 22, 46)` | `rgb(28, 40, 74)` | `rgba(14, 22, 54, 0.28)` |

## 5. Verified CC0 1.0 Universal Attribution

- **Credits**: `Pixel art and tiles: Kenney Vleugels (Kenney.nl) - Roguelike Indoors, Roguelike Characters, RPG Urban Pack, Tiny Town, UI Pack Pixel Adventure (CC0 1.0 Public Domain).`
- **License**: `CC0-1.0` (https://creativecommons.org/publicdomain/zero/1.0/)
- **Paid / Commercial / Ripped Assets**: `False`

| Pack ID | Title | Asset File | Source URL |
| :--- | :--- | :--- | :--- |
| `kenney-roguelike-indoors` | Roguelike Indoors | `docs/arena/assets/kenney_roguelike_indoor.png` | https://kenney.nl/assets/roguelike-indoors |
| `kenney-roguelike-characters` | Roguelike Characters 2.0 | `docs/arena/assets/kenney_roguelike_char.png` | https://kenney.nl/assets/roguelike-characters |
| `kenney-rpg-urban-pack` | RPG Urban Pack 1.0 | `docs/arena/assets/kenney_rpg_urban_packed.png` | https://kenney.nl/assets/rpg-urban-pack |
| `kenney-tiny-town` | Tiny Town 1.1 | `docs/arena/assets/kenney_tiny_town_packed.png` | https://kenney.nl/assets/tiny-town |
| `kenney-ui-pack-pixel-adventure` | UI Pack - Pixel Adventure 2.0 | `docs/arena/assets/kenney_ui_badges/` | https://kenney.nl/assets/ui-pack-pixel-adventure |
