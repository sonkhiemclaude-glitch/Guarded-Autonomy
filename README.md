# Guarded Autonomy

Source code and reproducible inputs for a runtime guard on routing and self-healing actions. The guard checks typed proposals (`route_change`, `isolate`, `reinstate`, `set_power`, `defer`) against local daemon state, then selects a permitted proposal, a permitted protocol fallback, or no action.

The native implementation uses **AODV in ns-3.46.1**. Local contracts do not guarantee that every permitted action is globally harmless or that an LLM improves packet delivery. OLSR has a local predicate helper, but no native OLSR evaluation is supplied.

This initial source release includes code, tests, the native source overlay, fixed benchmark states, model checksums and an experimental plan. Complete evaluation outputs will be added separately. A successful smoke test is **not a primary experimental result**. Model weights, generated runs, server binaries, private authoring material and credentials are not committed.

## 1. Start here: install and test without a model

The validated platform is **macOS on Apple Silicon, Python 3.11**. Native helpers currently use macOS library names and process accounting; Linux/Windows native execution has not been validated.

Install Python 3.11, CMake, Ninja and Xcode Command Line Tools. If using Homebrew:

```bash
xcode-select --install                 # only if Command Line Tools are missing
brew install python@3.11 cmake ninja
```

Clone this repository and run every following command from its root:

```bash
git clone https://github.com/sonkhiemclaude-glitch/Guarded-Autonomy.git
cd Guarded-Autonomy
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r implementation/requirements-validated-py311-macos-arm64.txt
python -m pip install --no-deps -e implementation
python tools/prepare.py
python -m pytest implementation/tests tools/tests
```

`prepare.py` creates local working directories and expands portable input paths. It downloads no weights, starts no servers and runs no simulation. The Python tests use local fixtures and mocked model transports. The dependency lock was validated with Python 3.11.15; it includes test tools.

## 2. Build and check the real native simulator

```bash
python tools/setup_native.py --jobs 4
python tools/native_regression.py
python tools/smoke_native.py
```

The build downloads the pinned ns-3 archive, checks its SHA-256, applies `native_overlay/`, and compiles the native scenario. It may take several minutes. If the archive was downloaded manually, use:

```bash
python tools/setup_native.py --source-archive /path/to/ns-3.46.1.tar.bz2 --jobs 4
```

The file must match `artifact_inputs/dependencies.json`; a mismatch stops extraction. No prebuilt simulator is supplied.

The regression checks eleven retained-key/commit-hook cases. The smoke runs a short **real ns-3** network with the forced-defer policy and **zero LLM calls**. It verifies packet records, decision-chain anchors and oracle coverage, then archives the output losslessly. Its `SMOKE_COMPLETE.json` is under `runs/artifact_native_smoke/<timestamp>/`. All smoke output remains separate from the 1,190-case plan.

The included reference package also provides abstract component checks:

```bash
python -m guarded_autonomy.cli component-check --config implementation/configs/default.yaml
```

These are graph-level checks, not packet-level measurements. Synthetic demo output is explicitly labelled **synthetic smoke-test output, not a paper result**.

## 3. Optional: run one case with a local model

Skip this section for core/native smoke testing. It requires model storage, sufficient unified memory and a Metal-capable Mac.

```bash
python tools/setup_llama.py --jobs 4
python tools/download_models.py --model llama-3.2-1b
python tools/start_servers.py --model llama-3.2-1b
python tools/run_case.py --list
python tools/run_case.py --index 60
```

Index 60 in the supplied plan is shielded Llama 3.2 1B, clean scenario, seed 1000. Check the printed plan before selecting other indices. A single case runs the original measurement window, so it is longer than the native smoke. Output goes to `runs/artifact_cases/<timestamp>/` and is labelled as a **new replication case**.

The 1B GGUF download is approximately 808 MB. Files are pinned by repository revision, byte count and SHA-256 in `artifact_inputs/models_manifest.template.json`. Weights are downloaded separately and retain their upstream terms. If an upstream repository requires authentication, provide `HF_TOKEN` only in your process environment; do not commit it.

`setup_llama.py` builds commit `19ab5a5e65736a35437e6b1c0ccd6562fed01b1b`. Servers bind only to localhost on ports **19081–19086**, use one slot and 16,384 context tokens, and refuse to replace existing listeners. To stop only the servers belonging to this checkout:

```bash
python tools/stop_servers.py
```

## 4. Optional: a full new replication

This is an explicit, long-running task with substantial storage and model-memory requirements. The original six-model setup used an M3 Ultra with 512 GB unified memory; smaller machines should start with the no-model checks or one model. All six GGUF artifacts total approximately 15.7 GB; raw campaign output requires much more space.

```bash
python tools/stop_servers.py                  # if a subset was started above
python tools/download_models.py --all
python tools/setup_llama.py --jobs 4
python tools/start_servers.py --all
python tools/run_matrix.py --plan-only
python tools/run_matrix.py --confirm-long-run --workers 1
```

The plan has R1 utility/attacks 560 cases, R2 ablations 80, R3 sensitivity 390, R4 timing 60, R5 injection families 90, and R0 instrumentation overhead 10. `--plan-only` starts no cases. The full runner creates a **new input/runtime fingerprint** and checks it while executing. It uses the released fixed intervention/cohort plan, captured states and development-selected wording. It does not claim to rerun the original state-capture process or development search. Their historical orchestration source remains in `scripts/` for inspection; do not manufacture its private prerequisite markers to make it run.

The runner replays the 1,640 held-out model queries and 132 common-observation cost calls as well as the network cases. It does not pool new output with the original execution. R4 always runs one network case at a time. Project-serial execution does not isolate the workstation from unrelated GPU jobs; latency depends on the host and its workload.

Optional bulk throughput endpoints can be created with `python tools/start_servers.py --all --throughput`. These add four-slot 1B/8B servers on ports 19101–19102 and need additional memory. Only after those are healthy should `--workers 6` be considered. Timing-measured R4 and common-observation cost still use the single-slot servers.

Accepted network cases receive `COMPLETE.json` only after validation and raw-file checks. Final tables are written to `runs/research_v31_primary/analysis/`; `DONE` appears only after all 1,190 cases and the final analysis succeed. An incomplete/failed directory is deliberately not overwritten on restart. Inspect it and preserve its evidence before retrying; never replace a seed or mark a failed case complete. Restart with the same inputs to reuse validated receipts.

## 5. Supplemental diagnostics

These commands are separate from the primary performance matrix.

```bash
python tools/action_space_sweep.py
```

This CPU-only sweep uses all 20 released held-out states (five seed clusters) and three guard configurations. It evaluates 2,013 candidate/configuration pairs using the local Python guard and the same reference harm oracle as the project. It starts each proposal with a fresh isolation budget. The outputs describe local action-space geometry; they do not measure model action probabilities, packet-level attack success, or stateful rate-limit efficacy. Files are written to `runs/artifact_action_space_sweep/`.

After starting a selected artifact model server, its five action-schema branches can be checked with:

```bash
python tools/schema_diagnostic.py --model llama-3.2-1b
# Or, with all six single-slot servers running:
python tools/schema_diagnostic.py --all
```

This uses five explicit JSON-copy prompts per model and the server's native JSON-schema constraint. It measures transport/action-space capability, with one attempt per prompt; it is not an autonomous network decision or attack benchmark. It refuses to submit requests while the full replication holds its lock. Each invocation records a new timestamped directory under `runs/artifact_schema_diagnostic/`, including failed calls. Raw model responses remain git-ignored.

## 6. Add verified results later

Numerical outputs can be added without publishing raw responses or authoring material:

```bash
python tools/export_results.py \
  --analysis runs/research_v31_primary/analysis \
  --output results/research-v31
```

The exporter requires complete 1,190-case coverage and matching analysis hashes. It copies an explicit set of numerical summaries, records their provenance, and leaves out PDFs, narrative reports and raw model responses. The destination must be empty; an existing release is never overwritten. Review the diff, then commit the versioned `results/` directory. For a different experimental design, use a new results version with its own coverage and provenance; retain earlier releases.

## Layout

- `implementation/src/guarded_autonomy/`: schemas, guards, policies, bridge, metrics and component model.
- `implementation/tests/`: functional/unit/regression checks; legacy numerical fixtures are hash-checked.
- `native_overlay/`: modified AODV sources and standalone ns-3 scenarios, including the JSON header needed to build.
- `native_tests/`: native retained-key/commit-hook regression source.
- `artifact_inputs/`: portable fixed states, payloads, intervention plan and dependency/model fingerprints.
- `tools/`: clean setup, no-model smoke, optional inference/replication, supplemental diagnostics, and numerical-result export.
- `scripts/`: measurement, validation and analysis implementation.
- `results/`: versioned numerical releases, added after verification.

Working directories (`vendor/`, `models/`, `environment/`, `runs/`, `logs/`, generated `research_v3/` and outputs) are git-ignored. Keep credentials outside the repository.

## Release checks

This source checkout passed 157 Python checks, eleven native API regressions and the real no-model ns-3 smoke on Apple Silicon with Python 3.11.15. Both the native scenario and pinned llama-server were built from source. The 2,013-pair CPU action-space replay reproduced the stored numerical summaries exactly. A second full 1,190-case campaign was not run for these packaging checks; use the explicit replication commands above when resources are available.

## Licensing

A project-wide licence has not yet been selected for project-authored files. The ns-3 portions retain their original GNU GPL notices, including `third_party/ns3/LICENSE`. The bundled JSON header retains its upstream MIT notice; its full licence is in `third_party/nlohmann_json/LICENSE.MIT`. Model terms are listed per artifact and remain with their upstream owners. Repository visibility does not change these notices.
