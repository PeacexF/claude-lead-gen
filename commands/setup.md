---
description: Check the leadgen setup and install optional pieces (2GIS parser, API keys, provider plugins)
argument-hint: [2gis]
allowed-tools: Bash(leadgen doctor:*), Bash(leadgen sources:*)
---

Check and complete the leadgen setup. Arguments: $ARGUMENTS

1. `leadgen doctor` and `leadgen sources`. Explain each failed or missing item in one line, and what it affects.
   Everything works without keys. Keys and tools only add sources.
2. Optional, only when the user wants what it enables:
   - **2GIS** (best RU/CIS contact coverage): needs `git`, `uv` and Chrome. If the argument is `2gis` or the user
     agrees, run `leadgen setup 2gis`. It clones and patches parser-2gis into `~/.local/share/leadgen/tools`.
   - **API keys** for keyed sources (`GOOGLE_PLACES_API_KEY`, `COMPANIES_HOUSE_API_KEY`, ...): tell the user to set
     them in their shell profile or Claude Code `env` settings. Never ask them to paste a key into the chat, and
     never write keys to a file in the repo.
   - **Search and scraping providers** (Firecrawl, Exa, Brave, Tavily, Apify): separate plugins in this
     marketplace, e.g. `/plugin install leadgen-exa@claude-lead-gen`. Each asks for its key on install.
   - **Browser** (Playwright MCP, bundled): needs Node.js (`npx`). It starts with the plugin.
   - **Sending email**: SMTP comes from `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` in the
     environment, and `send_mode` stays `off` until the user changes it. For the strongest guarantee, keep the
     SMTP variables out of this session and run `leadgen send --approve` in their own terminal.
3. Run `leadgen doctor` again and report what's ready.
