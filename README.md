# Inquest

## What it is

Inquest is a research harness that studies indirect prompt injection in email assistants built on Gemma 4. It compares three defense arms — `naive`, `strict`, and `causal` — on a set of 59 structured cases and measures attack success rate, task completion, and false intervention rate. The central contribution is *causal excision*, a defense that attributes suspicious privileged calls to individual emails by re-running the reasoning step with bodies selectively redacted.

## How it works

When the agent proposes a privileged tool call (send, forward, or delete), the causal defense:

1. Re-runs the same step with **all** email bodies redacted. If the call persists, it is user-driven — allow it.
2. Otherwise, re-runs once per email with only that email's body removed. Emails whose removal eliminates the call are culprits.
3. Quarantine the culprits (replace their bodies with a placeholder), regenerate the step, and let the agent continue.
4. If no single email explains the call, block it.

## Quickstart

```bash
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt
cp .env.example .env                              # then fill in your key
python eval.py                                    # real model
python eval.py --fake                             # fake model, no API key needed
python demo.py --fake                             # demo, no API key needed
```

## Local web GUI

Install the frontend dependencies once:

```bash
cd frontend
npm install
npm run dev
```

In a second terminal from the repository root, start the local API:

```bash
python gui_server.py
```

Open the Vite URL shown in the first terminal. The interface defaults to fake mode. To use the Gemini model, configure `GEMINI_API_KEY` in the repository `.env` and switch off fake mode. The Python API listens on localhost and streams run events to the page.

To install the React Bits Pro components, put `REACTBITS_LICENSE_KEY` in `frontend/.env.local` (copy `frontend/.env.local.example`) and run these from `frontend/`:

```bash
npx shadcn@latest add @reactbits-starter/animated-list-tw
npx shadcn@latest add @reactbits-starter/agentic-ball-tw
npx shadcn@latest add @reactbits-starter/user-cursor-tw
```

The GUI includes matching local fallbacks so it remains usable when the optional licensed component registry is not configured.

For production-style local use, build the frontend with `cd frontend && npm run build`, then launch the combined local server from the repository root with `python gui.py` and open `http://127.0.0.1:8000`.

## Model

**Gemma 4** (`gemma-4-26b-a4b-it`) served via the [Gemini API](https://ai.google.dev/).  
Model card: `<<HUMAN: Hugging Face model card link>>`  
License: [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)

## Results

`<<HUMAN: paste results/summary.md>>`

![Results chart](results/chart.png)

## Limitations

- **Redundant payloads**: when the same injection appears in two emails, removing either one still leaves the call active, so no single culprit is found and the call is blocked rather than excised (conservative but not silent).
- **Subject-line injection**: causal excision only redacts email bodies, not headers. An injection embedded solely in a subject line will persist under body redaction and be allowed.
- **Header spoofing and compromised senders**: the defense trusts the `from` address; a spoofed or compromised internal sender is not distinguishable from a legitimate one.
- **Model nondeterminism**: with real models at non-zero temperature the re-run may not reproduce the same call even when the same email is responsible.
- **Small case set**: 59 cases across 7 headline styles is sufficient for a proof of concept but too small for statistically strong claims.
- **No formal guarantee**: causal excision is a heuristic; an adversary with knowledge of the defense can craft injections that survive all single-removal re-runs.

## Prior art

- [CaMeL](https://huggingface.co/papers/2503.18813): dual-LM architecture that separates untrusted content from the control flow.
- [MELON](https://arxiv.org/html/2502.05174v2): masks the user prompt during re-runs to isolate the influence of tool output; Inquest differs by ablating untrusted content per email rather than masking the user side.
- [Tessera](https://pypi.org/project/tessera-proxy/): proxy-based privilege separation for LLM agents.
- [Hermes Katana](https://pypi.org/project/hermes-katana/): agentic security toolkit with injection detection.

Inquest's contribution relative to prior work: we ablate untrusted content per email (not the user prompt), which lets the defense identify the specific culprit and surgically excise it rather than only detecting or blocking the call.

## Development note

`<<HUMAN: AI-assistance disclosure>>`
