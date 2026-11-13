# Rules for every agent in this repo
- Silas Wang is team lead. A coordinator assistant assigns work and reads reports in docs/reports/<role>.md. Read CHALLENGE.md first.
- Hard deadline: final submission Sun 15 Nov 10:00 Europe/Helsinki. Judges weight a working END-TO-END demo highest (30%): keep main always runnable end to end; thin vertical slice first, polish later.
- Work only on your branch team/<role> in your own worktree. Commit small. Never force-push, never rewrite main. Merge to main only when the coordinator asks. Agree interfaces via docs/interfaces.md (append, do not silently change others' contracts).
- Stack default unless the team agrees otherwise: Python 3.11+, FastAPI, Pydantic, SQLite, uv for envs; frontend small (Next.js or plain React/Vite). Expose agent-facing interface as OpenAPI + an MCP server.
- Secrets: VALIO_API_KEY and portal password live in .env (gitignored). Never commit them or print them in reports. Raw data files in data/ are gitignored (87 MB); load from there.
- Never invent API fields or data. Cite openapi.json, the schema or the data; otherwise write UNVERIFIED. Be polite to the mock API: batch up to 1000 ids per call, cache responses, no hammering.
- Keep docs/reports/<role>.md current: status, what works (verified vs untested), blockers, what you need Silas to decide.
