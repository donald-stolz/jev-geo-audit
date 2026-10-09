# Jev GEO Citability Audit

This project builds a local dashboard that discovers public pages from an authorised website and measures how easily their content can support concise, verifiable answers.

## Project flow

1. Start with twelve safe mock results.
2. Keep the OpenRouter key in a local `.env` file.
3. Discover public URLs through `robots.txt` and sitemap files.
4. Run a five-page real-site pilot before starting Full Discovery across up to 600 pages.
5. Stop Full Discovery automatically after at least 20 attempts when fewer than 50 percent succeed.
6. Draft an improvement for the weakest successful page and export the evidence.

## Requirements

- Python 3.10 or later.
- A modern browser.
- Git, GitHub CLI, and Claude Code.
- A public website you own or have permission to audit.

## Local boundary

The server binds to `127.0.0.1:8000`. Python's `http.server` is used for learning and local testing only, not production hosting.

The crawler accepts public HTTP and HTTPS pages, respects `robots.txt`, and reads server-rendered HTML. It does not render JavaScript-only content.

Never place a real OpenRouter key in `index.html`, `styles.css`, or `app.js`.
