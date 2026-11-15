# Canary Arena Pixel-Art Asset Registry & License Manifest

All external pixel-art sprite sheets and UI badge icons vendored for Canary Arena live under `docs/arena/assets/` and are dedicated to the public domain under **Creative Commons Zero v1.0 Universal (CC0 1.0)**. Zero commercial, paid, or ripped game sprites are included anywhere in this repository.

## 1. Vendored Asset Packs, Authors, URLs, and Licenses

| Pack Title | Author | Source URL | License | Vendored Path | Dimensions & Tile Grid | Bytes | SHA-256 |
|---|---|---|---|---|---|---:|---|
| **Roguelike Indoors** | Kenney Vleugels (`Kenney.nl`) | https://kenney.nl/assets/roguelike-indoors | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `docs/arena/assets/kenney_roguelike_indoor.png` | `458x305` (`16x16` px, `1` px margin, `27x18`) | `22,169` | `ade984d5cbe3f16d9e23e6dc516246649de1a7eec2540cf31d53852b690c446f` |
| **Roguelike Characters 2.0** | Kenney Vleugels (`Kenney.nl`) | https://kenney.nl/assets/roguelike-characters | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `docs/arena/assets/kenney_roguelike_char.png` | `918x203` (`16x16` px, `1` px margin, `54x12`) | `11,137` | `771d51ca84b2c5b412027ba80c6a6b8a98bb5a983b2c58ac4f0ccf08ae4d10f2` |
| **RPG Urban Pack 1.0** | Kenney Vleugels (`Kenney.nl`) | https://kenney.nl/assets/rpg-urban-pack | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `docs/arena/assets/kenney_rpg_urban_packed.png` | `432x288` (`16x16` px, `0` px margin, `27x18`) | `17,300` | `305e71fa778444a0858c33988d45a6b79ea923f500f96079f4378347cf6ad389` |
| **Tiny Town 1.1** | Kenney Vleugels (`Kenney.nl`) | https://kenney.nl/assets/tiny-town | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `docs/arena/assets/kenney_tiny_town_packed.png` | `192x176` (`16x16` px, `0` px margin, `12x11`) | `5,042` | `3a54d99ecde790d4fdea207a3644cf130fc56fa838f1beb1507c185a95b8e902` |
| **UI Pack - Pixel Adventure 2.0** | Kenney Vleugels (`Kenney.nl`) | https://kenney.nl/assets/ui-pack-pixel-adventure | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `docs/arena/assets/kenney_ui_badges/badge_00..07.png` | `8` icons at `16x16` px | `1,227` | `62886a2569966c4a4507a74f2a052ffa721bda01b49b2a01f2271092bc286795` (`badge_00.png`) |

- **Total Vendored PNG Size:** **`56,875` bytes (`55.5 KB`)**, which is **0.38%** of the `15,000,000`-byte (`15 MB`) Arena asset budget.
- **Bundled License Text:** `docs/arena/assets/LICENSE-CC0-1.0.txt` (`CC0 1.0 Universal`: https://creativecommons.org/publicdomain/zero/1.0/).
- **Visible Page Credits Line (`#assetCredits`):**
  `Pixel art & tiles: Kenney Vleugels (Kenney.nl) - Roguelike Indoors, Roguelike Characters, RPG Urban Pack, Tiny Town, UI Pack Pixel Adventure (CC0 1.0 Public Domain).`

## 2. `OfficeStage.loadSpritePack` Integration & Coordinate Map

`docs/arena/assets/sprite_pack_manifest.json` conforms directly to `OfficeStage.loadSpritePack(manifest)` (`docs/arena/ui/office_stage.js`) and `mountArenaUI(root, adapters)` (`docs/arena/ui/arena_app.js`):

- **Tile coordinate formula (`kenney_roguelike_indoor.png` and `kenney_roguelike_char.png`):** `x = col * 17`, `y = row * 17`, `w = 16`, `h = 16` (`1 px` inter-tile margin).
- **Packed coordinate formula (`kenney_rpg_urban_packed.png` and `kenney_tiny_town_packed.png`):** `x = col * 16`, `y = row * 16`, `w = 16`, `h = 16` (`0 px` margin).
- **Primary Office Sprites (`manifest.sprites`):**
  - `desk`: `kenney_roguelike_indoor.png` `(col=8, row=0) -> (x=136, y=0, w=16, h=16)`
  - `meeting_table`: `kenney_roguelike_indoor.png` `(col=12, row=0) -> (x=204, y=0, w=16, h=16)`
  - `bistro_table`: `kenney_roguelike_indoor.png` `(col=13, row=0) -> (x=221, y=0, w=16, h=16)`
  - `coffee_bar`: `kenney_roguelike_indoor.png` `(col=9, row=0) -> (x=153, y=0, w=16, h=16)`
  - `chair`: `kenney_roguelike_indoor.png` `(col=18, row=0) -> (x=306, y=0, w=16, h=16)`
  - `plant`: `kenney_roguelike_indoor.png` `(col=16, row=0) -> (x=272, y=0, w=16, h=16)`
  - `server_rack`: `kenney_roguelike_indoor.png` `(col=14, row=0) -> (x=238, y=0, w=16, h=16)`
  - `security_console`: `kenney_roguelike_indoor.png` `(col=15, row=0) -> (x=255, y=0, w=16, h=16)`
  - `employee`: `kenney_roguelike_char.png` `(col=0, row=5) -> (x=0, y=85, w=16, h=16)`
  - `employee_alt`: `kenney_roguelike_char.png` `(col=1, row=5) -> (x=17, y=85, w=16, h=16)`
- **Visible Canary & Alert Items (`manifest.item_sprites`):**
  - `canary_doc_A`, `canary_doc_B`, `canary_doc_C` (`kenney_roguelike_indoor.png` cols `19`, `20`, `23`, row `0`) plus `badge_00..07.png` (`16x16` thick-outline UI icons).

## 3. Anti-Leak Integrity Contract

1. **Zero Hidden-Truth Leak Before Episode End:** `sprite_pack_manifest.json` locks `"leaking_sprite_employee": null`. All employee appearance and desk assignments depend exclusively on public roster fields (`employee_id`, `department`, `role`), never on `world.mole`, `world.decoy`, or the private world salt.
2. **Offline Deterministic Loading:** Every PNG is vendored locally under `docs/arena/assets/` with zero runtime network fetches to external CDNs for art assets and graceful procedural fallback in headless tests.
