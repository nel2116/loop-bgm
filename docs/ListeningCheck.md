# Listening check

<!-- last-reviewed: 2026-11-09 -->

An agent cannot judge how music sounds. The user listens at the end of each phase (spec section 11.6), not per PR.

## At the end of a phase (agent)

1. Render every example song under `songs/` with `python -m bgm render <song> --no-mp3`.
2. For each song that changed during the phase, keep the previous render (`songs/<song>/history/`) next to the new one.
3. Collect the 「試聴メモ」 sections of the phase's merged PRs.
4. Open one issue titled 「フェーズ N の試聴確認」 listing, per song: the file paths (old/new), what to listen for (from the notes), and a checkbox.
5. Ask the user to listen and write what bothered them in that issue.

## After the user listens (agent)

Split each remark into its own issue (`create-issue` skill), link them from the listening issue, and close the listening issue.

## What to listen for

- The seam: play the file on repeat (or a 3x concatenation); the jump back to the start should not be audible.
- Balance: the melody is audible but does not dominate; no part is much louder than the rest.
- Wrong notes: notes that clash with the chords.
- Monotony: whether the loop gets tiring after a few repeats.
