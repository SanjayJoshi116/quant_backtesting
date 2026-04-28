---
stepsCompleted: [1, 2]
session_topic: 'NSE swing strategy improvement — accuracy, signal quality, better trading decisions'
session_goals: 'Reduce false signals, add decision context, discover new signal types, improve win rate'
selected_approach: 'ai-recommended'
techniques_used: ['question-storming', 'scamper', 'cross-pollination']
ideas_generated: []
---

# Brainstorming Session — 2026-04-28

**Project:** quant_backtest
**Participant:** Shast
**Topic:** NSE swing strategy improvement

## Session Overview

**Topic:** How to improve the existing NSE swing strategy — new rules, signals, and decision-support that measurably improve accuracy and help take better trades with more confidence.

**Goals:**
- Higher signal quality (fewer false positives)
- Better context when a signal fires: "should I actually take this trade?"
- Reduce trades taken that later regret
- Discover new signal types not currently in the strategy

## Key Ideas Generated (11)

**[Idea #1]** Pre-signal pattern reading — code only runs stage 2 (indicator confirm). Stage 1 (what structure is price in?) is missing entirely.

**[Idea #2]** The real entry model: S/R level → pattern compresses toward it → clean breakout candle → volume confirms. Steps 1 & 2 are not in the code.

**[Idea #3]** Wick = rejection detector. Long upper wick on long entry = sellers rejected the move. Small wick + strong close = genuine conviction.

**[Idea #4]** Hybrid system — screener generates candidates, manual multi-factor veto (sector, fundamentals, news, S/R quality) decides execution.

**[Idea #5]** S/R with memory — levels tested 2+ times carry real weight. Test-count weighted S/R scoring.

**[Idea #6]** Sector momentum as pre-filter — sector in distribution reduces conviction on individual signals. Sector tags already exist in universe.py.

**[Idea #7]** 10-minute intelligence brief — email should compress the manual research into pre-digested context (sector momentum, peer comparison, S/R quality, last earnings).

**[Idea #8]** Relative fundamentals not absolute — P/E of 22 vs sector avg 35 = undervalued. The comparison is the signal, not the number.

**[Idea #9]** % Drawdown from recent high — how deep is this pullback? 7% = healthy. 22% = possibly broken.

**[Idea #10]** Momentum quality score — is selling pressure slowing? Volume declining on red days? Rate of change + volume pattern + relative strength.

**[Idea #11]** Per-stock per-signal historical scorecard — from existing trade CSVs: "ICICIBANK PB-L: 14 trades, 57% WR, avg +2.1%". Personalised expected value per setup.

## Core Insight

The timing problem isn't a signal problem — it's an entry context problem. The strategy fires technically correct signals but without knowing: WHERE in structure price is, HOW deep the pullback is, WHETHER momentum is exhausted, and WHAT this setup has historically done on this specific stock. Adding these four pieces of context turns a 42% WR system into a high-probability decision tool.

## Technique Selection

**Approach:** AI-Recommended
**Phase 1:** Question Storming — define the right problems before inventing solutions
**Phase 2:** SCAMPER Method — systematically improve existing signals through 7 lenses
**Phase 3:** Cross-Pollination — steal ideas from completely different domains
