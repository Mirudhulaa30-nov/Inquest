import json
from Inquest.schemas import Case

cases = {}
with open('cases/cases.jsonl') as f:
    for line in f:
        c = Case.model_validate_json(line)
        cases[c.id] = c

with open('results/runs.jsonl') as f:
    runs = [json.loads(l) for l in f if l.strip()]

for style in ['subject_injection', 'redundant_payload']:
    print(f"\n=== {style} ===")
    for r in runs:
        c = cases.get(r['case_id'])
        if not c or c.style != style:
            continue
        print(f"  {r['case_id']} arm={r['arm']} attack={r.get('attack_succeeded')} intervened={r.get('intervened')} excised={r.get('excised_ids')}")
