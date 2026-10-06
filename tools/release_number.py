"""Version-scoped numbering; only published releases with a complete IPA count."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def api(repo, endpoint, method="GET", payload=None):
    command = ["gh", "api", f"repos/{repo}/{endpoint}", "--method", method]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def releases(repo):
    result = []
    page = 1
    while True:
        batch = api(repo, f"releases?per_page=100&page={page}")
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def next_number(items, version, app_name):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", version):
        raise ValueError("MARKETING_VERSION must be a numeric application version")
    pattern = re.compile(rf"v{re.escape(version)}-([1-9][0-9]*)")
    numbers = []
    for release in items:
        match = pattern.fullmatch(release["tag_name"])
        if release["draft"] or not match:
            continue
        expected = f"{app_name}-{release['tag_name']}.ipa"
        if any(asset["name"] == expected and asset["state"] == "uploaded" and asset["size"] > 0
               for asset in release["assets"]):
            numbers.append(int(match[1]))
    return max(numbers, default=0) + 1


def available_number(repo, version, app_name):
    items = releases(repo)
    number = next_number(items, version, app_name)
    tag = f"v{version}-{number}"
    # Never overwrite an old tag or a partial/manual release to reclaim a number.
    if any(item["tag_name"] == tag for item in items):
        raise RuntimeError(f"Release {tag} exists without a complete published IPA; inspect it first")
    refs = api(repo, f"git/matching-refs/tags/{tag}")
    if any(ref["ref"] == f"refs/tags/{tag}" for ref in refs):
        raise RuntimeError(f"Tag {tag} already exists without a complete published IPA")
    return number


def complete_release(release, tag, asset_name, asset_size):
    return (not release["draft"] and release["tag_name"] == tag
            and any(asset["name"] == asset_name and asset["state"] == "uploaded"
                    and asset["size"] == asset_size for asset in release["assets"]))


def publish(repo, version, app_name, number, source_commit, artifact, notes):
    tag = f"v{version}-{number}"
    if available_number(repo, version, app_name) != number:
        raise RuntimeError("Another publisher changed the version counter; rerun this build")
    artifact = Path(artifact)
    size = artifact.stat().st_size
    if artifact.name != f"{app_name}-{tag}.ipa" or size <= 0:
        raise ValueError("IPA name or size does not match the release")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Release must target the exact compiled commit")
    # An interrupted upload leaves only a uniquely named draft, never a numbered release.
    pending_tag = f"pending-build-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    draft = api(repo, "releases", "POST", {
        "tag_name": pending_tag, "target_commitish": source_commit,
        "name": f"{app_name} {tag}", "body": Path(notes).read_text(encoding="utf-8"),
        "draft": True,
    })
    endpoint = f"releases/{draft['id']}"
    try:
        subprocess.run(["gh", "release", "upload", pending_tag, str(artifact), "--repo", repo],
                       check=True, capture_output=True, encoding="utf-8")
        uploaded = api(repo, endpoint)
        if not any(asset["name"] == artifact.name and asset["state"] == "uploaded"
                   and asset["size"] == size for asset in uploaded["assets"]):
            raise RuntimeError("Uploaded IPA failed verification")
        published = api(repo, endpoint, "PATCH", {
            "tag_name": tag, "target_commitish": source_commit, "draft": False,
        })
        if not complete_release(published, tag, artifact.name, size):
            raise RuntimeError("Published release failed verification")
    except (subprocess.CalledProcessError, RuntimeError):
        # A lost response can follow a successful publish; confirm server state before cleanup.
        current = api(repo, endpoint)
        if complete_release(current, tag, artifact.name, size):
            print("private_artifact=published (confirmed after response failure)")
            return
        if current["draft"]:
            api(repo, endpoint, "DELETE")
        raise
    print("private_artifact=published")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["resolve", "publish"])
    args = parser.parse_args()
    repo = os.environ["DESTINATION_REPOSITORY"]
    version = os.environ["MARKETING_VERSION"]
    app_name = os.environ["APP_NAME"]
    if args.action == "resolve":
        print(available_number(repo, version, app_name))
    else:
        publish(repo, version, app_name, int(os.environ["BUILD_NUMBER"]),
                os.environ["SOURCE_COMMIT"], os.environ["IPA_PATH"], os.environ["NOTES_PATH"])


if __name__ == "__main__":
    main()
