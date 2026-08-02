# Contributing

This is a design artifact first and a program second. The most valuable
contributions are usually not code.

## What helps most

**Testing it by ear, and saying what felt wrong.** This project exists because
speech that seems fine to a sighted developer is often unusable in practice.
If something made you want to switch it off, that is the report worth filing —
even without a cause or a fix.

**Native-speaker review of the strings.** `speechproto/strings.py` holds every
framing word — *maximum*, *item*, *of*, *submenu*. English is authoritative;
**the other languages were not written by native speakers and need to be.**
Getting "of" or a plural wrong in a screen reader is the difference between
fluent and grating. This is a small file and a large improvement.

**Porting the design.** The specification is the deliverable. An implementation
for other hardware, in another language, or against another state layer is the
best possible evidence that it is implementable.

**Arguing with `DESIGN.md`.** If a rule is wrong, say so and say why. Rules that
survive that are worth more than rules nobody questioned.

## If you are writing code

Read [DESIGN.md](DESIGN.md) first — particularly §14, which lists nine mistakes
already made and caught here. They are easy to make again.

Three rules the codebase enforces:

1. **The model never knows speech exists.** No engine, no verbosity, no wording
   in `params.py` or `instrument.py`. If you need to reach speech from there,
   the design is wrong, not the constraint.
2. **No user-facing string literals in `announce.py`.** Every word comes from
   `strings.py`, keyed by language. This is trivial on day one and near
   impossible to retrofit.
3. **Anything user-facing must be reachable with the screen off.** Not a
   metaphor. Turn it off and use the thing.

### Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run
```

Optional speech engines, both worth having:

```bash
brew install espeak-ng                     # or apt install espeak-ng
./.venv/bin/pip install -r requirements-piper.txt
cd voices && ../.venv/bin/python -m piper.download_voices en_US-lessac-medium
```

### Tests

```bash
./.venv/bin/python test_announcements.py
```

These assert the **exact strings in the DESIGN.md verbosity table**. The
specification is executable: if you change an announcement rule and the table
in `DESIGN.md` no longer matches, the tests fail. Change both, deliberately, or
neither.

## Licensing

Code contributions are under [Apache 2.0](LICENSE); documentation under
[CC BY 4.0](LICENSE-DOCS.md). By opening a pull request you agree your
contribution is licensed on those terms.

Apache 2.0 was chosen over MIT for two specific reasons: it carries an explicit
patent grant, which removes a reason for a corporate legal department to say
no; and its trademark clause means contributing code does not convey rights to
the project name.
