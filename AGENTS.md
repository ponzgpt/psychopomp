# psychopomp
Hermes Agent plugin: a dead man's switch that carries sealed letters. Entry for the Nous Hermes Agent Plugin Hackathon (due 2026-11-11 17:00 EST). Live: https://github.com/ponzgpt/psychopomp

## Commands
- Check (before every commit and push): `./scripts/check.sh`
- Dev: `ln -s "$PWD" ~/.hermes/plugins/psychopomp && hermes plugins enable psychopomp`
- Deploy: push to main, then bump `sha` in the catalog entry PR (`docs/catalog-entry.yaml` → NousResearch/hermes-agent `plugin-catalog/psychopomp.yaml`)

## Non-negotiables
1. Letters never leave without the trusted contact's code; keep that invariant tested in `tests/test_core.py`.
2. Sealed letter bodies never appear in any view, tool result or log.
3. Follow Nous' catalog rules (public surfaces only, no core patches, disclosures in README); not the usual technoir.cloud deploy rules.
4. Pareto: keep scope to the silence trigger; no date or event triggers until after the hackathon.
