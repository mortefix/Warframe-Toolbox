# Third-party assets shipped with Warframe Toolbox

Everything in this directory is here so the app can be handed to someone else
without a licensing question attached. If you add a bundled asset — a font, an
icon set, a sound, a data file — add its licence here and a row to the table.

## Material Symbols (icon font)

- **Files:** `../fonts/MaterialSymbolsSharp.ttf`
- **Upstream:** https://fonts.google.com/icons ·
  https://github.com/google/material-design-icons
- **Licence:** Apache License 2.0 — full text in `Apache-2.0.txt`
- **Copyright:** Copyright Google LLC
- **Modified:** no. The upstream variable font is shipped verbatim.

Used for every icon in the app. This replaced **Segoe Fluent Icons**, which
was the right call on three counts, only one of them cosmetic:

1. **Licensing.** The Segoe icon fonts ship with Windows and may not be
   redistributed, so an app that depends on them cannot be given away as a
   self-contained thing. Apache 2.0 can.
2. **Portability.** Segoe is Windows-only. On Linux every icon in this app
   would have fallen back to tofu — which matters, because moving there is a
   stated goal.
3. **Legibility of the code.** Segoe is addressed by Private Use Area
   codepoint — `""` — which is a number nobody can read and nobody can
   check. Two icons shipped wrong that way: `U+E82D` resolved to a CJK glyph
   in the Wiki button, and Segoe has no ribbon bookmark at all, so one had to
   be hand-painted. Material Symbols is addressed by **ligature**: the text
   `"menu_book"` renders the book. A typo now renders as a misspelt word
   rather than as a plausible-looking wrong picture.

The font is a **variable** font. The app uses the `FILL` axis (0 = outline,
1 = solid), which is how the bookmark ribbon shows saved vs unsaved as one
glyph at two axis values rather than as two drawings that can drift apart.

### Attribution requirement

Apache 2.0 §4(d): this NOTICE must travel with any redistribution. Keeping
this directory in the shipped tree satisfies that.

## Bundled text fonts (themeable UI faces)

These are the commercial-use-safe faces the app can draw the UI in. They are
selected per-theme through `core.theme.FONT_FACE` (see the `Dev-Fonts`,
`Dev-Boxes` and `Dev-Boundaries` themes) and loaded by `ui.icons.ensure_text_fonts`.
All are verifiable-provenance fonts from Google Fonts' own repository — the
license text ships with the file, which is exactly what a redistributable app
needs (unlike an aggregator's "free for commercial use" label with no license
attached). All but Mountains of Christmas are SIL Open Font License 1.1 (full
text in `OFL.txt`); Mountains of Christmas is Apache 2.0 (`Apache-2.0.txt`,
shared with Material Symbols).

| Font | File | Licence | Copyright |
|---|---|---|---|
| Be Vietnam Pro | `../fonts/BeVietnamPro-Regular.ttf` | OFL 1.1 | Copyright 2021 The Be Vietnam Pro Project Authors (github.com/bettergui/BeVietnamPro) |
| Marcellus | `../fonts/Marcellus-Regular.ttf` | OFL 1.1 | Copyright (c) 2012, Brian J. Bonislawsky DBA Astigmatic (AOETI) (astigma@astigmatic.com), Reserved Font Name "Marcellus" |
| Cormorant Garamond | `../fonts/CormorantGaramond-VF.ttf` | OFL 1.1 | Copyright 2015 The Cormorant Project Authors (github.com/CatharsisFonts/Cormorant) |
| Cinzel Decorative | `../fonts/CinzelDecorative-Bold.ttf` | OFL 1.1 | Copyright (c) 2012 Natanael Gama (info@ndiscovered.com), Reserved Font Name "Cinzel" |
| Spectral | `../fonts/Spectral-Medium.ttf` | OFL 1.1 | Copyright 2017 The Spectral Project Authors (github.com/productiontype/Spectral) |
| Orbitron | `../fonts/Orbitron-VF.ttf` | OFL 1.1 | Copyright 2018 The Orbitron Project Authors (github.com/theleagueof/orbitron), Reserved Font Name "Orbitron" |
| Rajdhani | `../fonts/Rajdhani-Regular.ttf` | OFL 1.1 | Copyright (c) 2014, Indian Type Foundry (info@indiantypefoundry.com) |
| Chakra Petch | `../fonts/ChakraPetch-Regular.ttf` | OFL 1.1 | Copyright 2018 The Chakra Petch Project Authors (github.com/m4rc1e/Chakra-Petch) |
| Exo 2 | `../fonts/Exo2-VF.ttf` | OFL 1.1 | Copyright 2013 The Exo 2 Project Authors (github.com/googlefonts/Exo-2.0) |
| VT323 | `../fonts/VT323-Regular.ttf` | OFL 1.1 | Copyright 2011, The VT323 Project Authors (peter.hull@oikoi.com) |
| Mountains of Christmas | `../fonts/MountainsofChristmas-Regular.ttf` | Apache 2.0 | Copyright (c) 2010, 2011 Font Diner, Inc DBA Tart Workshop (diner@fontdiner.com), Reserved Font Name "Mountains of Christmas" |

The OFL requires the copyright notice and licence to travel with the fonts, and
that a Reserved Font Name is not reused on a modified version. These files are
shipped **verbatim** (no modification), and this directory travels with them, so
both conditions hold.

## Anything else

| Asset | Where | Licence |
|---|---|---|
| `assets/logo.ico`, `logo.b64.txt` | app icon / crest | Warframe is © Digital Extremes. Fan-project use; not redistributed as a Digital Extremes work. |
| Platinum gem PNG (`core/assets.py`) | inline base64 | as above |
