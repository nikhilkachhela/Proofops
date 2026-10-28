"""Assemble the three kinds of evidence for one hypothesis, each with its provenance.

  TemporalPrecedence  - the cause happened before the first symptom
  DependencyPath      - a structural path links the cause to the symptomatic service
  CorroboratingSignal - a signal of a DIFFERENT kind agrees, on that path, after the cause
"""
from .contracts import allowed_signals

def assemble(store, hypothesis: dict, symptom_service: str) -> dict:
    onset_time, onset_id = store.symptom_onset()
    ev, notes = [], []
    cause_time = hypothesis.get("time")

    # 1. Temporal precedence
    if cause_time and onset_time and cause_time < onset_time:
        ev.append({"type": "TemporalPrecedence",
                   "detail": f"cause at {cause_time} precedes first symptom at {onset_time}",
                   "sources": [hypothesis["source"], onset_id]})
    else:
        notes.append(f"cause time {cause_time or 'unknown'} is not before first symptom {onset_time}")

    # 2. Dependency path
    target = f"service:{symptom_service}"
    path = store.dependency_path(hypothesis["object_id"], target)
    if path:
        ev.append({"type": "DependencyPath", "detail": " -> ".join(path), "path": path,
                   "sources": ["k8s_state.json", "calls.json"]})
    else:
        notes.append(f"no dependency path from {hypothesis['object_id']} to {target}")

    # 3. Corroborating signal (different modality, allowed type, on the path, after the cause)
    if path:
        allowed = allowed_signals(hypothesis["fault_type"])
        for s in store.signals_on(path):
            if s["signal_id"] == hypothesis["cause_id"] or s["modality"] == hypothesis["modality"]:
                continue
            if s["signal_type"] not in allowed:
                continue
            if cause_time and s["time"] < cause_time:
                continue
            ev.append({"type": "CorroboratingSignal",
                       "detail": f"{s['signal_type']} ({s['modality']}) on {s['on']} at {s['time']}: {s['quote']}",
                       "signal_type": s["signal_type"], "sources": [s["source"]]})
            break
        else:
            notes.append(f"no corroborating signal of an allowed type ({', '.join(sorted(allowed))}) on the path")

    return {"hypothesis": hypothesis, "evidence": ev, "notes": notes,
            "onset": onset_time, "symptom_service": symptom_service}
