"""Modern rewrite of python-semver's legacy module-level API."""

import re

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)"
    r"\.(?P<minor>0|[1-9]\d*)"
    r"\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+(?P<build>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")


def parse(version):
    """Parse a semver string into a dict (major/minor/patch/prerelease/build)."""
    match = _SEMVER_RE.match(version)
    if match is None:
        raise ValueError("%s is not valid SemVer string" % version)
    parts = match.groupdict()
    return {
        "major": int(parts["major"]),
        "minor": int(parts["minor"]),
        "patch": int(parts["patch"]),
        "prerelease": parts["prerelease"],
        "build": parts["build"],
    }


def _compare_prerelease(left, right):
    """semver.org 11.4: numeric identifiers compare numerically and rank
    below alphanumeric ones; a longer list wins over its own prefix."""
    left_ids = left.split(".")
    right_ids = right.split(".")
    for a, b in zip(left_ids, right_ids):
        a_num, b_num = a.isdigit(), b.isdigit()
        if a_num and b_num:
            if int(a) != int(b):
                return -1 if int(a) < int(b) else 1
        elif a_num:
            return -1
        elif b_num:
            return 1
        elif a != b:
            return -1 if a < b else 1
    if len(left_ids) != len(right_ids):
        return -1 if len(left_ids) < len(right_ids) else 1
    return 0


def compare(ver1, ver2):
    """-1, 0, or 1. Build metadata is ignored (semver.org 11.3)."""
    a, b = parse(ver1), parse(ver2)
    for key in ("major", "minor", "patch"):
        if a[key] != b[key]:
            return -1 if a[key] < b[key] else 1
    pre_a, pre_b = a["prerelease"], b["prerelease"]
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is None:
        return 1   # release > any of its prereleases
    if pre_b is None:
        return -1
    return _compare_prerelease(pre_a, pre_b)


def format_version(major, minor, patch, prerelease=None, build=None):
    version = "%d.%d.%d" % (major, minor, patch)
    if prerelease is not None:
        version += "-%s" % prerelease
    if build is not None:
        version += "+%s" % build
    return version


def bump_major(version):
    parts = parse(version)
    return format_version(parts["major"] + 1, 0, 0)


def bump_minor(version):
    parts = parse(version)
    return format_version(parts["major"], parts["minor"] + 1, 0)


def bump_patch(version):
    parts = parse(version)
    return format_version(parts["major"], parts["minor"],
                          parts["patch"] + 1)


def _increment_identifier(chain, default_token):
    """Recorded behavior: the RIGHTMOST identifier with a trailing digit
    run gets incremented in place (alpha.7.x -> alpha.8.x); a chain with
    no digits anywhere is returned UNCHANGED (bump_prerelease of
    '1.2.3-alpha' really is a no-op in the original)."""
    if not chain:
        return "%s.1" % default_token
    ids = chain.split(".")
    for index in range(len(ids) - 1, -1, -1):
        match = re.search(r"(\d+)$", ids[index])
        if match:
            ids[index] = (ids[index][:match.start()]
                          + str(int(match.group(1)) + 1))
            break
    return ".".join(ids)


def bump_prerelease(version, token="rc"):
    parts = parse(version)
    prerelease = _increment_identifier(parts["prerelease"], token)
    return format_version(parts["major"], parts["minor"], parts["patch"],
                          prerelease)


def bump_build(version, token="build"):
    parts = parse(version)
    build = _increment_identifier(parts["build"], token)
    return format_version(parts["major"], parts["minor"], parts["patch"],
                          parts["prerelease"], build)


def finalize_version(version):
    parts = parse(version)
    return format_version(parts["major"], parts["minor"], parts["patch"])
