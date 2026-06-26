#!/usr/bin/env python3

import state

print("Current state.historico:")
print(f"Length: {len(state.historico)}")
for i, item in enumerate(state.historico):
    print(f"  {i}: {item}")

print("\nCurrent state.jobs:")
print(f"Length: {len(state.jobs)}")
for k, v in state.jobs.items():
    print(f"  {k}: {v}")

print("\nCurrent state.processos:")
print(f"Length: {len(state.processos)}")
for k, v in state.processos.items():
    print(f"  {k}: {v}")