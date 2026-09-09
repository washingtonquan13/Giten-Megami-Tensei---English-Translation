# Presentation: why it looks rough in fullscreen, and what to do about it

Written 2026-09-09, from the question *"can we extract the sprites, upscale them
and put them back?"*

**Short answer: extraction is trivial, and putting upscaled art back would not
fix the problem.** The art is not what makes the game look rough on a modern
display; the fixed 640x480 8bpp output is. The fix belongs in a post-process
shader, not in the asset pipeline.

Claims are tagged **[measured]** or **[conjecture]**, same convention as
[`distribution.md`](distribution.md). Nothing here has been built or tested.

---

## 1. What the art actually is

**[measured]** Every file in `fc/` is a plain uncompressed Windows BMP. There is
no custom container, no compression, no encryption.

| | |
|---|---|
| BMP files in `fc/` | **1,577** |
| of those holding more than one image | **1,025** |
| bit depth | **8bpp on every single file, without exception** |

**[measured]** First-image dimensions:

| dimensions | files | what they are |
|---|---|---|
| 256 x 256 | 575 | dungeon wall textures |
| 640 x 480 | 133 | full-screen art |
| 640 x 400 | 106 | full-screen art (the PC-98 aspect) |
| 288 x 200 | 106 | portraits |
| 16 x 16 | 160 | icons |
| 32 x 32, 48 x 48, 32 x 24, 32 x 16, 16 x 24 | ~150 | small sprites |

So an extractor is a small job: read the BMP header, split the 1,025
multi-image files at each `BM` boundary, apply the palette, write PNG.

---

## 2. Why upscaling the assets does not solve it

Two walls. Both are now measured rather than assumed.

### The palette

**[measured]** All 1,577 files are **8bpp -- 256 colours**, with a palette per
file. Any upscaler worth using outputs 24-bit colour. Putting the result back
means re-quantising to 256 colours, which discards most of what the upscale
produced. Widening the palette is not a data change, it is a change to the
rendering path.

### The framebuffer

**[measured]** 640x480 is hardcoded in the display setup. `push 0x280` (640)
occurs 16 times in the image and `push 0x1E0` (480) exactly **four** times, and
two sites -- `0x00450AC9` and `0x00450C9B` -- push the pair twice each alongside
a flag and a surface pointer:

    push 1 ; push 480 ; push 640 ; push 480 ; push 640 ; push <ptr>

**There is no other resolution path in the binary.** The engine draws into a
640x480 8bpp surface and nothing else.

That makes the full-screen art (640x480, 640x400) *already native*. A 2560x1920
version of a background is downsampled straight back to 640x480 at blit time:
best case nothing changes, and **[conjecture]** more likely the blitter misreads
the dimensions and produces garbage, since sprite sizes look to be fixed by the
caller rather than read from the file. That last part has not been traced.

Raising the output resolution would mean rewriting the DirectDraw surface setup,
the dungeon renderer's texture maths and every hardcoded UI coordinate. That is
a different project, not an art pass.

---

## 3. The scaler config is already optimal

**[measured]** `play/en/ddswin/dgVoodoo.conf`:

    Resolution           = max_isf        <- maximum INTEGER scale factor
    Filtering            = pointsampled   <- nearest neighbour
    BilinearBlitStretch  = false
    Bilinear2DOperations = false
    ScalingMode          = centered_ar

That is the crispest presentation of a 640x480 image available. Together with
the game's own bilinear option already being off (`Config.exe` / `DevConfig`
byte 32, fixed earlier), there is no blur left to remove.

**So what is actually on screen is large, hard pixels** -- an honest 2x, 3x or
4x of the source, depending on the panel. That is inherent to 640x480, not a
misconfiguration, and no change to this file will improve it. Turning `Filtering`
back to bilinear trades blocky for soft; worth ten seconds to compare, but it is
the thing that was deliberately removed before.

---

## 4. The proposal: post-process shaders

Put the work after the frame is finished, where neither wall applies.

**ReShade layered over dgVoodoo2.** dgVoodoo2 presents through D3D11/12, which
ReShade hooks. Candidate shaders, in the order worth trying:

* **A CRT / scanline shader.** Usually the most pleasing result for art drawn in
  1997 at this resolution. It does not fight the blockiness, it makes it look
  intended. Try this first.
* **An edge-aware upscaler** -- xBRZ, ScaleFX, or similar. Built for exactly
  this problem: low-resolution art enlarged with interpolated edges rather than
  square blocks. Cleaner than bilinear, sharper than nearest.
* **A mild sharpen or anti-blockiness pass** if both of the above are too
  stylised.

Why this is the right layer:

* it operates on the final frame, so the 256-colour palette and the 640x480
  surface are both already behind it;
* it touches no game file, so it cannot interact with the translation, the
  overlay, the exe patches or the manifest checks in `distribution.md`;
* it is toggled with a key, so comparing is instant and reverting is free;
* it needs no engine work.

**[conjecture]** That ReShade hooks this particular dgVoodoo2 configuration
cleanly. It is the expected behaviour and dgVoodoo2 is a common ReShade target,
but it has not been tried here. This is the one thing to test before treating
any of section 4 as settled.

---

## 5. Alternatives considered and rejected

| idea | why not |
|---|---|
| AI-upscale the BMPs, put them back | 256-colour re-quantisation destroys the gain; output surface is 640x480 anyway (§2) |
| Raise the game's output resolution | 640x480 is hardcoded at `0x450AC9` / `0x450C9B`; would require rewriting surface setup, dungeon renderer and all UI coordinates |
| Widen the art to 24-bit | the engine is an 8bpp DirectDraw application throughout; this is an engine rewrite wearing an art-pass costume |
| Change dgVoodoo2 settings | already optimal (§3); the only remaining lever trades blocky for blurry |
| Redraw the art by hand at 640x480 | would genuinely work and needs no engine change, but it is 1,577 files and a different skill set. Not rejected on merit -- just enormous |

---

## 6. The one asset-side task still worth doing

An `fc/` extractor -- split the 1,025 multi-image files, apply palettes, write
PNGs. **Not built.** Its value is not upscaling:

* it makes the art *inspectable*, which is the only honest way to judge whether
  anything is worth redrawing by hand;
* **[conjecture]** some of the 239 full-screen images may have Japanese text
  baked into the bitmap, which no translation table covers and which would
  otherwise ship untranslated without anyone noticing. This has not been
  checked, and checking it is the strongest reason to build the extractor.

---

## 7. What to test, in order

1. **ReShade over dgVoodoo2** with a CRT shader. Settles §4, costs an evening,
   and is reversible.
2. `Filtering = bilinear` for ten seconds, purely as a comparison point.
3. Build the extractor and **look for baked-in Japanese** in the 239 full-screen
   images. This one matters to the translation regardless of how the
   presentation question lands.
