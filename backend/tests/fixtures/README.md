# tests/fixtures/

Small synthetic images for **unit tests only** — node tests need *some*
bytes to put in `GraphState.image`, but since node tests mock the
`ModelProvider` (no real Claude call happens), the image content is
never actually inspected. `placeholder.png` is a 2x2 solid-color PNG
generated from stdlib `zlib`/`struct`, not a real photo.

This is distinct from `backend/evals/fixtures/`, which holds real
photos of real wine and Halloween items, photographed by a human, with
hand-written ground-truth JSON sidecars — see CLAUDE.md's "Evals"
section. Never substitute this directory's synthetic images for real
eval fixtures, and never treat a passing unit test here as evidence of
real model accuracy.
