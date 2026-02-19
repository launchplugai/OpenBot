# fixit.bot — Product Design Concept

> *"I don't care what anything was designed to do. I care about what it CAN do."*
> — Gene Kranz, Apollo 13 Flight Director

> *"A crow doesn't study aerodynamics. It watches, remembers, and tries things
> with sticks until the grub comes out."*
> — The Fixit Principle

---

## 0. One-Liner

A self-training lateral-thinking model — raised like a crow, not shipped like
software — that finds what linear diagnostics miss by learning YOUR system's
failure patterns over time.

---

## 1. The Problem

Traditional diagnostics are **transactional**. They check known failure modes
against known thresholds:

```
Is CPU > 90%?        → scale up
Is disk > 80%?       → clean up
Is response > 500ms? → optimize query
```

This catches **expected failures**. It misses everything else:

- The config file that works today but breaks on Feb 29
- The env var that leaks a provider nobody asked for
- The session dir that grows 1MB/hr and kills the box at 3am Tuesday
- The model chain that's "working" but costing 6x because fallback ordering is wrong
- The two microservices that are both correct individually but deadlock together

These are **emergent failures** — they live in the gaps between components,
in the statistical noise, in the assumptions nobody questioned.

**fixit.bot doesn't check what's broken. It asks what COULD break, what
SHOULDN'T work but does, and what works but SHOULDN'T.**

And it gets better at asking every single day.

---

## 2. The Crow Model

### Why a Crow

Crows have small brains — 10g, about the size of a walnut. But they:

- **Solve multi-step problems** (bending wire to make hooks)
- **Use tools** and modify them (trimming sticks to fish for grubs)
- **Remember faces** for years (recognize individual humans as threat/friend)
- **Teach their young** (pass knowledge across generations)
- **Cache strategically** (hide food, remember 200+ locations)
- **Play** (slide down snowy roofs for fun — aka exploration/curiosity)
- **Hold grudges** (remember and avoid past threats)

This is fixit.bot. Small model. Disproportionate intelligence. Learned, not
programmed.

### The Training Philosophy

fixit.bot is **not a prompt wrapper around Haiku**. It STARTS as Haiku-guided
but incrementally trains its own model — a small, specialized network that
learns YOUR system's specific failure patterns.

The training is **spaced, measured, and intentional**. Like raising an actual
crow:

```
Week 1:   Imprinting    — Show it the codebase. "This is home."
Week 2-4: Observation   — It watches signals silently. Builds baselines.
Month 2:  First hunt    — It starts finding anomalies. Many false positives.
Month 3:  Correction    — Operator labels: "good find" / "noise". Model adjusts.
Month 4:  Tool use      — It learns which reasoning frames work for which signals.
Month 6:  Teaching      — It can explain WHY something is weird, not just THAT it is.
Month 12: Independence  — The crow hunts alone. Haiku is backup, not primary.
```

**Bang for the buck**: A fine-tuned 1B parameter model that knows YOUR stack
intimately will outperform a 200B general model that's never seen your configs.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        fixit.bot                             │
│                                                              │
│  ┌─────────┐   ┌───────────┐   ┌──────────┐   ┌─────────┐  │
│  │ SIGNALS │──→│  CROW      │──→│PRESCRIP- │──→│ OUTPUT  │  │
│  │         │   │  ENGINE    │   │TIONS     │   │         │  │
│  │ logs    │   │            │   │          │   │ json    │  │
│  │ metrics │   │ Phase 1:   │   │ ranked   │   │ md      │  │
│  │ configs │   │  Haiku 4.5 │   │ fixes    │   │ github  │  │
│  │ code    │   │  (teacher) │   │ w/ conf  │   │ telegram│  │
│  │ state   │   │            │   │ + blast  │   │ slack   │  │
│  │ git     │   │ Phase 2:   │   │ + reversi│   │         │  │
│  │         │   │  Own model │   │          │   │         │  │
│  │         │   │  (the crow)│   │          │   │         │  │
│  └─────────┘   └─────┬─────┘   └──────────┘   └─────────┘  │
│       ↑              │                                       │
│       │         ┌────▼────────────────────┐                  │
│       │         │    LEARNING LOOP        │                  │
│       │         │                         │                  │
│       │         │  ┌──────────┐           │                  │
│       │         │  │ MEMORY   │ Training  │                  │
│       │         │  │ (corvid  │ samples   │                  │
│       │         │  │  cache)  │ labeled   │                  │
│       │         │  └────┬─────┘ over time │                  │
│       │         │       │                 │                  │
│       │         │  ┌────▼─────┐           │                  │
│       │         │  │ SPACER   │ Spaced    │                  │
│       │         │  │ (repetit-│ intervals │                  │
│       │         │  │  ion)    │ like a    │                  │
│       │         │  └────┬─────┘ real pet  │                  │
│       │         │       │                 │                  │
│       │         │  ┌────▼─────┐           │                  │
│       │         │  │ TRAINER  │ Fine-tune │                  │
│       │         │  │ (incre-  │ when ready│                  │
│       │         │  │  mental) │ not before│                  │
│       │         │  └──────────┘           │                  │
│       │         └─────────────────────────┘                  │
│       │                                                      │
│  ┌────┴──────────────────────────────────────┐               │
│  │          STANDARD DEVIATION               │               │
│  │   Continuous anomaly detection on ALL     │               │
│  │   signals. Not thresholds — statistical   │               │
│  │   outliers. The "active ball" that never  │               │
│  │   stops rolling through the distribution. │               │
│  └───────────────────────────────────────────┘               │
│                                                              │
│  ┌───────────────────────────────────────────┐               │
│  │          PLUGINS                          │               │
│  │   openbot | openclaw | fastapi | django   │               │
│  │   k8s | bare-metal | (any stack)          │               │
│  └───────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 The Two-Phase Brain

**Phase 1: Haiku as Teacher (Months 1-6)**

Haiku runs the reasoning. Every scan produces:
- Input: signals snapshot
- Output: prescriptions
- Label: operator feedback ("good find" / "noise" / "critical")

This generates **training pairs**. The crow is watching the teacher work.

**Phase 2: Own Model (Month 6+)**

When enough labeled data accumulates (target: 2,000 labeled pairs),
fine-tune a small model (1-3B params, quantized to INT8). This model:
- Runs locally (no API cost)
- Responds in <100ms (no network latency)
- Knows YOUR system specifically
- Falls back to Haiku for novel situations

**The crow never fully leaves the teacher.** Haiku remains available for
situations the crow hasn't seen before. But for the 80% of patterns that
recur, the crow handles it instantly and for free.

### 3.2 Design Constraints

1. **Start Haiku, grow into own model.** Never skip the learning phase.
2. **No state between scans.** Memory is persistent storage, not runtime state.
3. **No actions.** Prescribes only. Never executes fixes. Doctor, not surgeon.
4. **Modular.** Works inside OpenBot. Works standalone. Zero hard dependencies.
5. **Simple.** Core engine <500 lines. Intelligence is in the model, not the code.
6. **Measured training.** Spaced repetition. Never rush. Quality > quantity.

---

## 4. The Six Reasoning Frames

These are the lateral thinking patterns. Each is a different lens on the same
signals. Traditional diagnostics use Frame 1 only. The crow learns which
frames work best for which signal patterns.

### Frame 1: INVERSION (What shouldn't work but does?)
```
"Look at everything that IS working. Ask: WHY does it work?
If the answer is 'I don't know' or 'by accident' — that's
a future failure hiding as current success."
```

### Frame 2: CONSTRAINT (What do we HAVE?)
```
"Ignore what we wish we had. List only what exists: RAM,
disk, processes, packages, env vars, ports, APIs.
Now: what can these BECOME?"
```

### Frame 3: ANALOGY (What does this remind me of?)
```
"Compare the current system state to known failure patterns
from OTHER systems. Not the same system — different ones.
Cross-pollinate."
```

### Frame 4: TEMPORAL (What changes when time passes?)
```
"Freeze every variable except time. Fast-forward 1 hour,
1 day, 1 week, 1 month. What breaks?"
```

### Frame 5: REMOVAL (What if we deleted this?)
```
"For each component: what happens if it vanishes?
'Nothing' = dead weight. 'Everything breaks' = SPOF."
```

### Frame 6: EDGE (What's the standard deviation telling us?)
```
"Ignore the mean. Focus on the tails. What's 2σ+ from
normal? That's where failures incubate."
```

---

## 5. The Learning Loop

### 5.1 Training Data Collection

Every scan generates a training sample:

```json
{
  "id": "scan-2026-02-19-001",
  "timestamp": "2026-02-19T14:32:00Z",
  "signals": { ... },
  "prescriptions": [
    {
      "frame": "inversion",
      "title": "Anthropic provider active without explicit config",
      "confidence": 0.94,
      "blast_radius": "medium"
    }
  ],
  "labels": null
}
```

### 5.2 Labeling (the operator interaction)

Labels come from operators — the human in the loop:

```bash
fixit label scan-2026-02-19-001
# Shows the prescription, asks:
#   [1] Good find (correct diagnosis)
#   [2] Noise (false positive)
#   [3] Critical (underrated severity)
#   [4] Wrong frame (right problem, wrong reasoning)
```

Labels are **spaced**. OpenClaw schedules labeling sessions:

```
Day 1:    Label today's scans (immediate feedback)
Day 3:    Re-label Day 1 scans (did the fix work?)
Day 7:    Review the week (pattern recognition)
Day 30:   Monthly retrospective (what keeps coming back?)
```

### 5.3 The Spaced Repetition Schedule

Modeled on the Leitner system (flashcard-based spaced repetition):

```
Box 1: New patterns      → review every scan
Box 2: Seen once         → review every 3 scans
Box 3: Seen 3+ times     → review every 10 scans
Box 4: Well-known        → review every 50 scans
Box 5: Mastered          → review on regression only
```

When the crow gets a pattern right, it moves to the next box (less frequent
review). When it gets one wrong, it drops back to Box 1.

**This prevents catastrophic forgetting** — the model keeps reviewing old
patterns at decreasing frequency, just like how crows periodically check
their cached food locations.

### 5.4 Incremental Fine-Tuning

Training happens in stages, not all at once:

```
Stage 1 (100 labeled pairs):   Prompt engineering only (few-shot examples)
Stage 2 (500 labeled pairs):   LoRA adapter on Haiku distillation
Stage 3 (2000 labeled pairs):  Full fine-tune of 1-3B base model
Stage 4 (5000+ labeled pairs): Quantized deployment model (INT8, local)
```

**OpenClaw controls the pace.** It decides when to advance stages based on:
- Label quality (inter-annotator agreement if multiple operators)
- False positive rate (<15% to advance)
- Recall on known-critical patterns (>90% to advance)
- Calendar time (minimum 2 weeks between stages — no rushing)

---

## 6. How It Runs

### 6.1 On-Demand Scan

```bash
fixit scan                         # scan current directory
fixit scan /path/to/project        # scan specific project
fixit scan --frame inversion       # run only one frame
fixit scan --output json           # machine-readable output
fixit scan --plugin openbot        # use OpenBot-specific signals
```

### 6.2 Watch Mode (the active ball)

```bash
fixit watch                        # scan every 5 minutes
fixit watch --interval 60          # scan every 60 seconds
fixit watch --alert telegram       # send alerts to Telegram
fixit watch --threshold 0.7        # only alert confidence > 0.7
```

### 6.3 Label Training Samples

```bash
fixit label                        # label the next due sample
fixit label --batch 10             # label 10 samples
fixit label --review               # re-label due for spaced review
fixit label scan-2026-02-19-001    # label a specific scan
```

### 6.4 Training Status

```bash
fixit status                       # show crow development stage
```
```
╔══════════════════════════════════════════╗
║  fixit.bot — Crow Status                ║
╠══════════════════════════════════════════╣
║  Age:            34 days                ║
║  Stage:          2 (LoRA adapter)       ║
║  Training pairs: 847 labeled            ║
║  Next stage at:  2,000 pairs            ║
║                                         ║
║  Accuracy:  78% (was 61% at Stage 1)    ║
║  FP rate:   12% (threshold: <15%)       ║
║  Recall:    84% (threshold: >90%)       ║
║                                         ║
║  Leitner Boxes:                         ║
║    Box 1 (new):      23 patterns        ║
║    Box 2 (seen):     67 patterns        ║
║    Box 3 (familiar): 41 patterns        ║
║    Box 4 (known):    12 patterns        ║
║    Box 5 (mastered):  4 patterns        ║
║                                         ║
║  Brain: Haiku 4.5 + LoRA adapter        ║
║  Cost today: $0.003                     ║
║  Lifetime:   $2.41                      ║
╚══════════════════════════════════════════╝
```

### 6.5 As a Library

```python
from fixit import Crow

crow = Crow("/root/.openclaw/")         # point at your system
crow.load_plugin("openbot")             # stack-specific signals

prescriptions = crow.scan()             # run all 6 frames

for rx in prescriptions:
    print(f"[{rx.confidence:.0%}] {rx.title}")

# Label for training
crow.label("scan-001", verdict="good_find")

# Check development
print(crow.status())
```

---

## 7. Plugin Interface

A plugin teaches the crow about a specific stack. Two methods: what to
observe, and what to know.

```python
from fixit.plugin import Plugin, ContextHint
from fixit.signals import FileSystem, Process, Http, EnvVars

class OpenBotPlugin(Plugin):
    name = "openbot"
    version = "0.1.0"

    def signals(self):
        return [
            FileSystem("/root/.openclaw/", watch=["*.json", "*.md"]),
            Process("openclaw-gateway"),
            Http("http://localhost:18789/", interval=30),
            EnvVars(watch=["*_API_KEY", "OPENCLAW_*"]),
        ]

    def context(self):
        return [
            ContextHint("Session files grow without bounds"),
            ContextHint("Gateway takes ~50s to start"),
            ContextHint("ANTHROPIC_API_KEY in shell env causes auto-discovery"),
            ContextHint("Config must be writable or EPERM crash"),
            ContextHint("Model chain: Kimi → Claude → GPT-4o-mini"),
        ]
```

---

## 8. Cost Model (Bang for the Buck)

| Phase | Brain | Cost/Scan | Cost/Day (5min) | Cost/Month |
|-------|-------|-----------|-----------------|------------|
| Stage 1 | Haiku (few-shot) | ~$0.003 | ~$0.86 | ~$26 |
| Stage 2 | Haiku + LoRA | ~$0.002 | ~$0.58 | ~$17 |
| Stage 3 | Own model (API) | ~$0.001 | ~$0.29 | ~$9 |
| Stage 4 | Own model (local) | ~$0.000 | ~$0.00 | ~$0 |

**By Stage 4, the crow runs for free on local hardware.** The entire
training investment is <$100 over 6 months. That's the bang.

---

## 9. The Apollo 13 Principle

On April 14, 1970, the Apollo 13 CO2 scrubbers failed. Square canisters,
round holes. The engineers built an adapter from cardboard, plastic bags,
duct tape, and a sock.

They didn't order new parts. They looked at what they HAD and asked:
**"What can this BECOME?"**

fixit.bot's core algorithm:

```
1. Don't ask "what's wrong?"     → Ask "what's weird?"
2. Don't ask "what's the fix?"   → Ask "what do we HAVE?"
3. Don't ask "is this optimal?"  → Ask "is this SURVIVING by accident?"
```

And the crow's addition:

```
4. Don't ask "what did the textbook say?" → Ask "what worked LAST TIME?"
5. Don't train on everything              → Train on what MATTERS
6. Don't rush the learning                → Space it. Measure it. Respect it.
```

---

## 10. What fixit.bot Is NOT

- **Not a monitoring tool.** Datadog watches thresholds. The crow watches distributions.
- **Not an auto-fixer.** It prescribes. It never acts. Doctor, not surgeon.
- **Not a code reviewer.** It reads signals ABOUT code, not code itself.
- **Not a big model.** The whole point is a small, specialized brain.
- **Not rushed.** If training is hurried, the crow learns noise. Patience is a feature.
- **Not expensive.** $0/month at full maturity. That's the goal.

---

## 11. Roadmap

| Phase | What | Investment |
|-------|------|-----------|
| **0.1** | Core engine + 6 frames + CLI + training data collection | Now |
| **0.2** | Labeling CLI + spaced repetition scheduler | +2 weeks |
| **0.3** | Watch mode + Telegram alerts | +4 weeks |
| **0.4** | Stage 2: LoRA adapter (when 500 labels) | ~Month 2-3 |
| **0.5** | GitHub Actions + community plugins | +8 weeks |
| **0.6** | Stage 3: Own model fine-tune (when 2000 labels) | ~Month 4-5 |
| **0.7** | Stage 4: Quantized local deployment | ~Month 6 |
| **1.0** | Independent crow. Haiku as backup only. | ~Month 8-12 |

---

## 12. Name

**fixit.bot** — because the best engineer in the room isn't the one who
knows the most. It's the one who looks at a sock and sees a CO2 filter.

And the best model isn't the biggest. It's the one that knows YOUR system
by heart because it was raised there, slowly, with care, one scan at a time.

---

*"We're raising a very smart crow. Bang for the buck."*
