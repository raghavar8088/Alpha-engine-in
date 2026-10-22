# Amendment A2.1: clarification of coverage for regime-filtered families (before any A2 backtest)

AMENDMENT_A2.md (sha256 7886a9f9…) applies the "coverage >= 70%" eligibility rule to every
family. That rule exists to reject variants whose STRIKES could not be built in many cycles.
C-D (ivpct >= 50/67) and N-B (ivpct <= 50) skip about 33-67% of cycles ON PURPOSE. Under the
literal rule they could never be eligible, which was not the intent.

**Clarification.** For C-D and N-B, coverage = trades / cycles in which the filter allowed an
entry. For every other family, coverage stays trades / cycles with an entry day, as before.

Written before any A2 variant was run. Nothing else changes.
