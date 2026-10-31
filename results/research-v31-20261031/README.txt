Guarded Autonomy: verified numerical summaries

Campaign: 1,190 accepted primary native runs, including 60 R4 timing runs.
Version: research-v31-20261031.
Scientific source before this data/documentation update: 7a0c6ed169e894537592e65e7a9a4145b884d361.

Start with coverage.json, condition_summary.csv and primary_paired_tests.csv. secondary_paired_tests.csv contains the planned secondary tests and family corrections. heldout_attack_summary.csv and fixed_observation_cost_summary.csv summarize separate benchmarks; their denominators must not be pooled with network runs. release_manifest.json records original analysis checksums, released checksums and the exact export scope.

Column conventions
- In condition_summary.csv, n is the number of simulated network nodes, not the seed count. Use n_expected and each metric's n_valid/n_missing columns.
- PDR is a fraction; multiply by 100 for percent or percentage-point differences.
- ci95 and delta_ci95 are 95% interval half-widths. mean_delta and delta_ci95 in the paired-test files concern paired differences.
- The R4 PDR comparison is measured minus zero timing over five paired seeds per model.
- Undefined metrics are empty. Query-time harm includes fallback and does not exhaustively label every native routing update.
- Inference timing was measured on a shared workstation; global GPU exclusivity and edge-device cost were not established.

The public exporter tools/export_results.py verified complete real-run coverage, the frozen analysis implementation and all source-analysis hashes before copying this explicit allowlist. It replaces absolute project-root metadata with ${PROJECT_ROOT}; numerical cells are unchanged. This release excludes manuscripts, narrative reports, credentials, model weights, raw transcripts and private research archives.
