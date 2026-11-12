# ADR 0043 — Disambiguate month names and clause-local negation

The verifier reads a month such as May as a calendar cue when it occurs in a date. A negated second clause can coexist with a supported positive claim about the first clause. The lexical check accepts the first clause when it matches the source and the negation modifies only the second clause. Actor and scope checks still apply.

The challenge caught all 176 planted errors with the deterministic checks alone and with MiniCheck. The development comparison showed no improvement in overall correctness. Broader scope across citations was rejected because nearby sentences did not establish the intended antecedent.
