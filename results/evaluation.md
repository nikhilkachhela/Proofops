# ProofOps evaluation

Answer key used for scoring only. Dev = 17 cases used to write rules; test = 43 held-out cases never inspected while writing rules.

## test

| Metric | Value |
|---|---|
| cases | 43 |
| baseline_acc@1 | 9% (4/43) |
| graph_acc@1 | 23% (10/43) |
| proofops_acc@1 | 77% (33/43) |
| proofops_acc@3 | 81% (35/43) |
| proofops_class_acc | 72% (31/43) |
| evidence_closure | 58% (25/43) |
| supported_and_correct | 80% (20/25) |
| graph_right_but_unproven | 7% (3/43) |
| graph_wrong_but_claimed | 77% (33/43) |
| missing_evidence | {'CorroboratingSignal': 10, 'TemporalPrecedence': 10, 'DependencyPath': 1} |

## dev

| Metric | Value |
|---|---|
| cases | 17 |
| baseline_acc@1 | 12% (2/17) |
| graph_acc@1 | 29% (5/17) |
| proofops_acc@1 | 88% (15/17) |
| proofops_acc@3 | 94% (16/17) |
| proofops_class_acc | 71% (12/17) |
| evidence_closure | 65% (11/17) |
| supported_and_correct | 82% (9/11) |
| graph_right_but_unproven | 12% (2/17) |
| graph_wrong_but_claimed | 71% (12/17) |
| missing_evidence | {'TemporalPrecedence': 3, 'CorroboratingSignal': 4} |

## all

| Metric | Value |
|---|---|
| cases | 60 |
| baseline_acc@1 | 10% (6/60) |
| graph_acc@1 | 25% (15/60) |
| proofops_acc@1 | 80% (48/60) |
| proofops_acc@3 | 85% (51/60) |
| proofops_class_acc | 72% (43/60) |
| evidence_closure | 60% (36/60) |
| supported_and_correct | 81% (29/36) |
| graph_right_but_unproven | 8% (5/60) |
| graph_wrong_but_claimed | 75% (45/60) |
| missing_evidence | {'TemporalPrecedence': 13, 'CorroboratingSignal': 14, 'DependencyPath': 1} |

## Test set by category

| Category | Cases | Component acc@1 | Class acc | Supported |
|---|---|---|---|---|
| admission | 4 | 75% (3/4) | 75% (3/4) | 50% (2/4) |
| codedefect | 9 | 56% (5/9) | 0% (0/9) | 89% (8/9) |
| infrastructure | 3 | 67% (2/3) | 67% (2/3) | 67% (2/3) |
| performance | 1 | 0% (0/1) | 100% (1/1) | 0% (0/1) |
| runtime | 3 | 100% (3/3) | 100% (3/3) | 100% (3/3) |
| scheduling | 14 | 86% (12/14) | 93% (13/14) | 43% (6/14) |
| service | 3 | 67% (2/3) | 100% (3/3) | 33% (1/3) |
| startup | 6 | 100% (6/6) | 100% (6/6) | 50% (3/6) |
