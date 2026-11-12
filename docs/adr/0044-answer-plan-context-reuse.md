# ADR 0044 — Reuse the planner context when drafting

The legacy answer path plans the response before writing it. The writer reuses the planner's Ollama context size when the writer prompt and output allowance fit. Keeping the same context size avoids reloading the generator between these calls. The writer can grow the context when its payload needs more room.

This changes context allocation only. The generation schema, answer checks and citation rules are the same.

In three interleaved CPU pairs, raw replies and displayed answers were identical. Reusing the context reduced writer model load time from 8.9–9.1 seconds to below 0.01 seconds. Median wall time fell by 13.31 seconds, with individual changes ranging from a 13.44-second reduction to a 7.61-second increase.
