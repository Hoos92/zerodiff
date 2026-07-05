"""Exercises python-semver (github.com/python-semver/python-semver) —
the semver.org precedence rules that everyone implements wrong.

    retrace record -o traces -- python run_scenarios.py
"""

import warnings

warnings.simplefilter("ignore")  # legacy API emits DeprecationWarning

import retrace  # noqa: E402

for fn in ("compare", "parse", "bump_major", "bump_minor", "bump_patch",
           "bump_prerelease", "bump_build", "finalize_version",
           "format_version"):
    retrace.wrap("semver", fn)

import semver  # noqa: E402

# ordered by precedence per semver.org §11 (build metadata ignored)
ORDERED = [
    "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
    "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0",
    "1.0.0+build.99", "1.9.0", "1.10.0", "1.11.0", "2.0.0-rc.1+b7",
    "2.0.0", "10.0.0",
]

VALID_PARSE = ["0.0.0", "1.2.3", "1.2.3-rc.1", "1.2.3+b7",
               "1.2.3-rc.1+build.7", "10.20.30",
               "1.2.3-alpha-dash.7", "1.1.2-prerelease+meta"]

INVALID_PARSE = ["1.2", "1.2.3.4", "01.2.3", "1.02.3", "1.2.03",
                 "1.2.3-01", "", "a.b.c", "1.2.3-", "1.2.3+",
                 "1.2.-3", "v1.2.3", "1.2.3 "]


def main():
    calls = 0
    raised = 0
    for a in ORDERED:
        for b in ORDERED:
            semver.compare(a, b)
            calls += 1
    for text in VALID_PARSE:
        semver.parse(text)
        calls += 1
    for text in INVALID_PARSE:
        calls += 1
        try:
            semver.parse(text)
        except ValueError:
            raised += 1
    for version in ("1.2.3", "1.2.3-rc.1+b7", "0.0.9", "9.9.9-alpha"):
        for bump in (semver.bump_major, semver.bump_minor,
                     semver.bump_patch):
            bump(version)
            calls += 1
    for version in ("1.2.3", "1.2.3-rc.1", "1.2.3-rc.9", "1.2.3-alpha",
                    "1.2.3-alpha.7.x", "1.2.3-rc.1+b7"):
        semver.bump_prerelease(version)
        calls += 1
    for version in ("1.2.3", "1.2.3+build.1", "1.2.3+build.42",
                    "1.2.3-rc.1+b.9", "1.2.3+7"):
        semver.bump_build(version)
        calls += 1
    for version in ("1.2.3-rc.1+b7", "1.2.3", "1.2.3+b7", "1.2.3-alpha"):
        semver.finalize_version(version)
        calls += 1
    semver.format_version(1, 2, 3)
    semver.format_version(1, 2, 3, "rc.1")
    semver.format_version(1, 2, 3, "rc.1", "build.7")
    semver.format_version(1, 2, 3, None, "build.7")
    calls += 4
    print("scenarios: %d calls (%d raised)" % (calls, raised))


if __name__ == "__main__":
    main()
