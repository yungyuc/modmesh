# Speed Up Pull-Request CI

## Goal

Cut the wall-clock time a contributor waits for pull-request (PR) CI to turn
green, and cut the GitHub-hosted runner minutes each PR spends, **without**
losing the coverage the project relies on. The strategy is twofold: make the
work that must run on every PR faster (compiler caching, dedup), and move the
work that rarely changes or does not gate correctness off the PR path into the
nightly schedule.

Measured baseline (warm, upstream): a PR turns green in ~13 minutes, gated by
the `build_windows` Release job, at ~115 runner-minute-equivalents per PR. The
cold tail reaches ~45 minutes. The plan targets a warm critical path of a few
minutes and trims ~30-40 runner-minute-equivalents per PR by caching the
Windows compile, dropping PR-only rebuilds, and pushing rarely-changing work to
nightly. A `master` push runs only the fast pull-request set, enough to
re-verify the merge and warm the shared caches that pull requests restore, but
not the full nightly suite. The heavy, slowly-drifting checks run on the
nightly schedule only. The end-state split of jobs:

- Run on every pull request and `master` push (kept fast):
  - `check_skip`: skip gate, also auto-skips the C++ matrix for docs-only or
    Python-only PRs
  - `lint`: formatting, flake8, and clang-tidy on the diff (ubuntu, macOS)
  - `standalone_buffer`: the standalone buffer build (ubuntu)
  - `build`: gtest plus pytest with Qt off and on, and the pilot (ubuntu and
    macOS, Release)
  - `build_windows` Release: Windows build and tests, with sccache and no
    portable packaging
- Run nightly only (scheduled):
  - `build_windows` Debug: the second Windows configuration
  - `nouse_install`: the `setup.py install` packaging path (ubuntu, macOS)
  - a real ASAN/UBSAN sanitizer build
  - `profiling`: the benchmark suite (already nightly)
  - Windows portable: the distributable artifact packaging

The nightly run is the superset: the fast set plus these extras, which
preserve the coverage that moves off the PR path.

## Plan

Three phases, landed in order. Each phase is implemented and measured on a
personal fork first, compared against the Appendix A baseline, then ported to
the upstream repository once its exit criterion is met. Steps are numbered
continuously across phases. Each tag marks whether it shortens **wall-clock**
(contributor wait), **cost** (runner minutes), or both. Phase 1 is the priority
because it owns the critical path. Phases 2 and 3 can proceed in parallel with
each other once Phase 1 lands.

### Phase 1: shorten the warm critical path

Goal: take the warm PR critical path from ~13m toward a few minutes by killing
the uncached Windows compile and the PR-only fat around it. All edits are in
`devbuild.yml` unless noted.

1. **Add sccache to `build_windows` (wall-clock + cost).**
   [sccache](https://github.com/mozilla/sccache) is a ccache-like shared
   compiler cache that also wraps MSVC `cl.exe`. Add it via
   `hendrikmuhs/ccache-action` with `variant: sccache` to the job and pass
   `-DCMAKE_C_COMPILER_LAUNCHER=sccache -DCMAKE_CXX_COMPILER_LAUNCHER=sccache`
   to the `cmake` configure step. Pair it with
   `-DCMAKE_MSVC_DEBUG_INFORMATION_FORMAT=Embedded` (i.e. `/Z7`) so debug info
   is embedded in objects and is cacheable instead of going to a shared PDB.
   This turns most of the 574s `ALL_BUILD` compile (Appendix A) into cache
   hits, the single biggest lever for the warm critical path. _Target:
   Windows Release ~13m -> a few minutes warm._

2. **Move Windows portable packaging off the PR path (wall-clock + cost).**
   Gate the `generate portable` and `archive portable artifacts` steps (and
   their second pilot build) on `github.event_name == 'schedule'` so they run
   nightly/release only. _Removes one full pilot rebuild plus downloads from
   every PR Windows Release run._

3. **Delete the no-op sanitizer step from the PR `build` job (wall-clock +
   cost).** The final `make cmake USE_SANITIZER=ON & make pytest` step passes
   `-DUSE_SANITIZER=OFF`, so it is a redundant full rebuild + pytest with no
   sanitizer coverage. Remove it from the PR path. Its real ASAN/UBSAN form is
   restored in Phase 2, step 7. _Removes ~1 full build per `build` job._

4. **Gate the heavy matrix behind the fast checks (cost, some wall-clock).**
   Add `needs: [check_skip, lint]` to `build`, `build_windows`, and
   `nouse_install` (or introduce a dedicated fast "smoke" compile job). A
   format/flake8/clang-tidy failure then short-circuits before the Windows
   build launches, instead of burning it in parallel.

_Exit criterion:_ a warm PR shows `build_windows` Release at a few minutes
with `sccache --show-stats` reporting hits, and the PR critical path is
visibly below the ~13m baseline. Then port Phase 1 to upstream.

### Phase 2: trim runner-minute cost

Goal: cut the ~115 runner-minute-equivalents/PR by moving rarely-changing and
duplicated work to the nightly `schedule` trigger, without touching the
critical path. These jobs move to `schedule` only, *not* `master` pushes,
which keep running just the fast PR set to re-verify the merge and warm caches.

5. **Move the Windows Debug build to nightly (cost).** Gate the
   `cmake_build_type: Debug` Windows matrix entry on `schedule` only. Keep only
   Windows Release on PRs and `master` pushes. _Removes ~16 (warm) to ~70
   (cold) runner-minute-equivalents per PR and reduces queue pressure._

6. **Move `nouse_install` off the PR path, at least its macOS leg (cost).** It
   re-verifies `setup.py install` and duplicates the `build` job's pytest. The
   macOS leg is the worst cost offender (~1.1m wall-clock billed at 10x, a third
   macOS compile after `build` and `lint`). Restrict it to `schedule` plus the
   pre-release/tag path. _Removes ~16 runner-minute-equivalents per PR and one
   whole macOS compile._

7. **Restore a real sanitizer build in nightly (coverage).** Re-add the step
   removed in step 3 as a genuine `-DUSE_SANITIZER=ON` ASAN/UBSAN build under
   the `schedule` trigger, where the longer run is acceptable. `profiling` is
   already correctly nightly-gated (`schedule` + `MMGH_NIGHTLY`). Use it as the
   template.

_Exit criterion:_ a warm PR drops ~30-40 runner-minute-equivalents versus the
Appendix A baseline, and the nightly run carries Windows Debug, the install
path, and the sanitizer build green. Then port Phase 2 to upstream.

### Phase 3: kill the cold tail and remaining redundancy

Goal: make the warm case the *common* case (the cold tail is where contributor
pain actually is) and remove duplicate per-OS builds and toolchain rebuilds.

8. **Auto-skip the C++ matrix for docs-only / Python-only PRs (wall-clock +
   cost).** Add a `dorny/paths-filter` (or `paths`/`paths-ignore`) gate so a PR
   touching only `doc/**`, `*.md`, or `solvcon/**` (no `cpp/**`, no build
   files) skips the C++ matrix automatically, instead of relying on a
   maintainer to apply `skip-ci`. This very PR (docs-only) is the motivating
   case.

9. **Cache or prebuild the toolchain (wall-clock + cost).** Stop building
   pybind11 from source in `setup_*`, and install the `pybind11` pip wheel
   (it already ships the CMake config). For gcc-16/clang-tidy-22/llvm@22, cache
   the apt/brew packages, or build a prebuilt container image in nightly and
   pull it in PR jobs, so the toolchain is not reassembled on every job.

10. **Pre-warm and stabilize the caches, the cold-tail fix (wall-clock).**
    Have the fast-set `build`/`build_windows` jobs save caches on their
    `master` push and nightly runs, so every PR restores a warm ccache/sccache,
    vcpkg, and Qt cache (GitHub lets a PR read its base branch's and the default
    branch's caches, the cache-warming role of the `master` push). Give
    each cache a `max-size` and a key that includes the compiler version so it
    does not thrash, and confirm the
    `vcpkg-${{ runner.os }}-openblas-lapack` cache reliably hits. A miss
    means OpenBLAS/LAPACK compiles from source, the bulk of the cold Windows
    tail (consider true vcpkg binary caching into the Actions cache). Document
    that PRs on a non-default base branch lose these caches and run cold.

11. **Consolidate redundant per-OS builds (cost).** macOS is built by `build`,
    `nouse_install`, and `lint`. After step 6, keep the matrices lean so each OS
    is compiled the minimum number of times a PR needs.

_Exit criterion:_ a docs-only PR finishes in seconds, and a cold PR (a branch
with no warm cache) restores caches instead of rebuilding OpenBLAS/LAPACK from
source. Then port Phase 3 to upstream.

## Validation notes

Each phase carries its own exit criterion above. These are the cross-cutting
gotchas when measuring them:

- **Compare against Appendix A.** Job durations from the GitHub Actions REST
  API (`/runs`, `.../jobs`) are the yardstick, and the per-phase targets are
  stated relative to those tables.
- **Non-default bases start cold.** A PR that targets a non-default base branch
  cannot restore the warmed caches (Appendix B, finding 6) and will look slow
  even after a fix lands. Validate the *warm* path on the upstream repository,
  or on a PR based off the default branch.
- **Watch the sccache stats.** MSVC + CMake + sccache is the most failure-prone
  piece of the plan. Confirm `sccache --show-stats` reports cache hits rather
  than silently falling through to full compiles.

## Appendix A: Measurements

Measured from the 100 most recent `solvcon/solvcon` Actions runs and the
test-drive PRs on a specific fork (causes in Appendix B):

- A typical upstream PR turns green in **~13 minutes**, gated by the
  `build_windows-2022` Release job, whose critical step is **9.6 minutes of
  MSVC compilation with no compiler cache**.
- That same job runs **up to 45 minutes** when caches are cold (as seen on a
  specific fork), because vcpkg then compiles OpenBLAS/LAPACK from source and
  PRs on a non-default base branch cannot read the warmed caches.
- A PR costs **~115 runner-minute-equivalents** (Linux 1x, Windows 2x, macOS
  10x). The macOS jobs, compiled three times per PR, dominate cost despite
  trivial wall-clock.

So **Windows compilation is the wall-clock target, redundant macOS is the cost
target, and cache pre-warming is the cold-tail fix.**

CI time on this project splits into two regimes, and conflating them hides the
real levers.

**Warm cache (the typical upstream PR).** Aggregated over the **100 most recent
`solvcon/solvcon` workflow runs** (a 26.8-hour window: 21 `devbuild`, 23
`lint`, 23 `nouse_install` runs that reached success/failure, plus cancelled
and skipped), the per-job medians are small and *stable*:

| Job (`devbuild`, Release unless noted) | median | max   | n  |
| -------------------------------------- | ------ | ----- | -- |
| `build_windows-2022` Release           | 12.9m  | 13.6m | 21 |
| `build_windows-2022` Debug             |  8.2m  |  8.8m | 21 |
| `build_ubuntu-24.04` Release           |  6.2m  | 10.5m | 21 |
| `build_macos-26` Release               |  3.0m  |  7.7m | 21 |
| `standalone_buffer` ubuntu             |  1.2m  |  5.2m | 21 |
| `lint` ubuntu (PR: clang-tidy-diff)    |  3.6m  | 15.3m | 23 |
| `lint` macOS                           |  2.0m  |  8.8m | 23 |
| `nouse_install` ubuntu                 |  4.9m  |  6.4m | 23 |
| `nouse_install` macOS                  |  1.1m  |  7.5m | 23 |

The PR "all-green" wall-clock is the slowest workflow, **`devbuild`, gated by
`build_windows-2022` Release at ~13 minutes**, with very low variance.

**Cold cache (the tail, seen on a specific fork).** Four recent feature-branch
PRs there (labelled #44-#47 below) ran the *same* workflows but 2-4x slower,
because their caches were cold or unreachable:

| Job (Release unless noted)       | #44    | #45    | #46    | #47    |
| -------------------------------- | ------ | ------ | ------ | ------ |
| `build_windows-2022` Release     | 17m35s | 22m26s | 38m05s | 44m48s |
| `build_windows-2022` Debug       | 35m58s | 11m36s | 35m21s | 35m57s |
| `build_ubuntu-24.04` Release     | 18m50s |  5m10s | 32m53s | 25m20s |
| `nouse_install` ubuntu           |  4m12s |  1m53s | 17m43s | 16m00s |
| `nouse_install` macOS            |  1m04s |    51s |  9m42s |  6m28s |

The same Windows Release job is 12.9m upstream and up to 44.8m on the fork. The
diffs are comparable in size, so **cache state, not the code, drives the swing**
(Appendix B, finding 6). The plan therefore has two distinct targets: shorten
the warm critical path (Windows compile), and make the warm case the *common*
case.

### Where the warm critical path goes (step-level)

Breaking down a warm `build_windows-2022` Release job (run 27907334049) shows
the time is almost all raw compilation, with no compiler cache to absorb it:

| Step                          | time |
| ----------------------------- | ---- |
| `cmake ALL_BUILD` (compile)   | 574s |
| `Cache vcpkg` (restore hit)   |  68s |
| `dependency by pip`           |  35s |
| `generate portable`           |  29s |
| `archive portable artifacts`  |  25s |
| `run_pilot_pytest`            |  12s |
| `install qt` (cache hit)      |  10s |

`cmake ALL_BUILD` alone is **9.6 minutes of MSVC compilation that nothing
caches**: vcpkg and Qt are cache hits, but the C++ objects are rebuilt from
scratch every run. That single step is the warm-cache long pole.

### Cost: runner-minute-equivalents per PR

GitHub bills minutes with OS multipliers (Linux 1x, Windows 2x, macOS 10x). The
public-repo billing API reports zero, so converting the measured wall-clock per
PR gives the *equivalent* spend that a private/fork repo would pay:

| Workflow        | median equiv | max equiv |
| --------------- | ------------ | --------- |
| `devbuild`      | 78 min       | 126 min   |
| `lint`          | 21 min       | 26 min    |
| `nouse_install` | 16 min       | 80 min    |
| **total / PR**  | **~115 min** | n/a       |

The macOS 10x multiplier is the hidden cost: a 3-minute macOS job costs 30
equivalent minutes, so the macOS jobs (compiled three times per PR: `build`,
`lint`, `nouse_install`) dominate cost despite trivial wall-clock. **Windows is
the wall-clock target, and redundant macOS is the cost target.**

## Appendix B: Findings

The PR critical path is the slowest job. The findings below explain both the
warm-case cost and the cold-case blow-up.

### 1. Windows has no compiler cache (biggest single cost)

`devbuild.yml` adds `hendrikmuhs/ccache-action` to the Linux and macOS `build`
jobs, but the `build_windows` job has **no compiler caching at all**. Every
Windows run recompiles the entire C++ codebase with MSVC from scratch, twice
(Release and Debug). The step-level breakdown (Appendix A) confirms it: even
with vcpkg and Qt as cache hits, `cmake ALL_BUILD` is **574 seconds (9.6 min)
of uncached compilation**, which is the entire warm critical path. It is also
why the Windows Release time is so *stable* upstream (12.9-13.6m): with
nothing to cache, every run pays the same full-compile price. This is the
single biggest lever.

### 2. Windows Release rebuilds a second time to package a portable

After `build_windows` Release runs `ALL_BUILD`, `run_gtest`, and
`run_pilot_pytest`, the `generate portable` step **reconfigures and builds the
pilot target again** (`cmake --build build --config Release --target pilot`),
then downloads the Python embeddable, runs `get-pip`, installs PySide6, and
runs `windeployqt` to upload a distributable artifact. None of this gates
correctness. It is release packaging that runs on every PR. Warm, it adds
`generate portable` (29s) + `archive portable artifacts` (25s) ~= 1 min and an
artifact upload to every PR. Cold, the extra configure/build is larger. It is
modest next to the compile, but it is pure waste on the PR path.

### 3. The `build` job's sanitizer step is a wasted full rebuild

The last step of the Linux/macOS `build` job is labelled
`make cmake USE_SANITIZER=ON & make pytest`, but it actually passes
`-DUSE_SANITIZER=OFF` (marked `FIXME: turn off until all issues resolved`). It
does `rm -f build/*/Makefile`, reconfigures, rebuilds the whole extension, and
re-runs pytest, a third full build per `build` job that currently adds **no
sanitizer coverage**. Because it flips CMake flags, ccache cannot reuse the
prior phase's objects.

### 4. Each PR builds the extension many times across jobs

For one PR the `_solvcon` extension is built from near-scratch in several
places that overlap:

- `build`: gtest (QT=OFF) -> buildext (QT=OFF) + pytest -> buildext (QT=ON) +
  pytest -> pilot -> sanitizer rebuild. The `rm -f build/*/Makefile` between
  QT=OFF and QT=ON forces a CMake re-run, and the QT define change invalidates
  much of the ccache, so this is effectively two-plus full builds.
- `nouse_install`: `setup.py install build_ext` builds the extension **again**
  (QT=OFF) on ubuntu and macOS, then runs the same pytest suite the `build`
  job already ran. On #46 this job alone took 17m43s on ubuntu.
- `standalone_buffer`: a separate (small) build.

The `nouse_install` job verifies the `setup.py install` packaging path, which
is valuable but rarely broken by a feature PR, and largely duplicates `build`.

### 5. Dependency setup is reinstalled from scratch on every job

`setup_linux` installs gcc-16 and g++-16 from `ppa:ubuntu-toolchain-r/test`,
clang-tidy-22 from the LLVM apt repo, Qt 6.8.1 via `install-qt-action`, several
pip packages, and **builds pybind11 from source** (`install.sh pybind11`),
every run, on every Linux job. `setup_macos` similarly `brew install llvm@22`
and builds pybind11. Qt is cached, but the toolchain/apt/brew/pybind11 work is
not, and it is paid once per job across 7+ jobs per PR.

### 6. Cold caches, not build growth, cause the 2-4x blow-up

The same `build_windows` Release job is 12.9m median upstream but 17-44.8m on
the fork. Ubuntu Release is 6.2m upstream but up to 32.9m on the fork. The
diffs are comparable, so the swing is cache state, and two mechanisms explain
it:

- **vcpkg from source.** When the `vcpkg-${{ runner.os }}-openblas-lapack`
  cache misses, `vcpkg install openblas lapack` *compiles* OpenBLAS and LAPACK
  from source (many minutes) instead of the 68s restore + 2s install seen
  warm. This is the bulk of the cold Windows tail.
- **Cache scope across branches.** GitHub Actions restores a cache only from
  the PR branch, its base branch, and the default branch. The fork's PRs target
  a feature branch, not the default branch, so they cannot read the
  master-warmed ccache/vcpkg/Qt caches and start cold every time.

Stabilizing and pre-warming the caches (Plan, step 10) removes most of the
worst-case minutes, which is where contributor pain actually is.

### 7. Every PR runs the full matrix regardless of what changed

CI gating is all-or-nothing: the only way to skip the heavy jobs is the manual
`skip-ci` label or `[skip-ci]` control string (`check_skip_ci.yml`). A
docs-only or Python-only PR still launches the full Windows/macOS/Linux C++
matrix unless a maintainer remembers to label it.

## Sources

- Timing data: the 100 most recent `solvcon/solvcon` Actions runs and their
  job/step durations, via the GitHub Actions REST API
  (`/repos/solvcon/solvcon/actions/runs`, `.../jobs`), 26.8-hour window ending
  2026-06-21, and four feature-branch PRs (#44-#47) on a specific fork for the
  cold-cache figures.
- sccache with CMake/MSVC and `CMAKE_CXX_COMPILER_LAUNCHER`:
  [mozilla/sccache](https://github.com/mozilla/sccache),
  [issue #957](https://github.com/mozilla/sccache/issues/957)
- ccache for CMake + MSVC:
  [ccache discussion #1104](https://github.com/ccache/ccache/discussions/1104)
- Cache scope across branches and runner-minute multipliers (Linux 1x,
  Windows 2x, macOS 10x): GitHub Actions docs on
  [cache restrictions](https://docs.github.com/actions/using-workflows/caching-dependencies-to-speed-up-workflows)
  and
  [billing for Actions](https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions).
- PR-vs-nightly split, path filtering, matrix trimming:
  [GitHub Actions performance optimization](https://oneuptime.com/blog/post/2026-02-02-github-actions-performance-optimization/view),
  [dorny/paths-filter usage](https://www.kleore.com/blog/github-actions-ci-optimization)

<!-- vim: set ft=markdown ff=unix fenc=utf8 et sw=2 ts=2 sts=2 tw=79: -->
