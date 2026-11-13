# DESIGN.md: Executive Briefing Folio Visual Identity

## Overview
- **Direction**: Courtroom / Executive Briefing Folio (`Exhibit A` vs. `Exhibit B`)
- **Typography**: `Fraunces` (display serif & MYR figures) + `Work Sans` (UI & body) + `Fira Code` (SQL, MCP code samples, and elapsed timing)
- **Themes**: `Paper` (warm newsprint bisque `#f6f0e6`, default for bright projector rooms) and `Espresso` (dark `#151210`)
- **Shape & Elevation**: `1px` sharp corners (`--radius: 1px`), tonal surface layers, crisp `1px` hairline borders, zero drop shadows

## Color Tokens (`frontend/app/tokens.css`)
| Token | Light (`Paper`) | Dark (`Espresso`) | Role |
| :--- | :--- | :--- | :--- |
| `--surface-0` | `#f6f0e6` | `#151210` | Page canvas |
| `--surface-1` | `#fffdf9` | `#1e1a17` | Exhibit A & Exhibit B deposition cards |
| `--surface-2` | `#eae0d1` | `#29231e` | Headers, sample buttons, drawer bars |
| `--ink-1` | `#1c1917` | `#f5efe6` | Primary text and primary button fill |
| `--ink-2` | `#524941` | `#bfb4a6` | Secondary labels and metadata |
| `--rule` | `#cfc3b2` | `#3d342d` | Hairline dividers |
| `--accent` | `#7a1c37` | `#f79cb8` | Burgundy seal for governed citations (`[§1]`..`[§3]`) |
| `--positive` | `#14532d` | `#6ee7b7` | Governed benchmark verdict (`Exhibit B`) |
| `--negative` | `#941b1b` | `#fca5a5` | Ungrounded distortion verdict (`Exhibit A`) |

All text tokens maintain WCAG AA/AAA contrast (`>= 6.61:1` across all surfaces).
