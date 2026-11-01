# Contributing

Thanks for helping! Issues and pull requests are welcome in English or Chinese.

- Ideas for the **next app in the series** go to the "Next app idea" issue template or Discussions.
- Run `cd server && python -m pytest` and `node --test web/test/` before a PR; UI changes should
  pass `scripts/e2e.sh` (Playwright, WebKit + Chromium).
- Never commit copyrighted audio, lyrics or stems, API keys, or personal data. Demo content must be
  public domain or CC0/CC-BY with attribution in THIRD_PARTY.md.
- The repository is laid out so other apps of the series can live next to Jam later
  (`server/cteno_jam`, `web/`, `e2e/` are Jam-specific; shared tooling lives in `scripts/`).
