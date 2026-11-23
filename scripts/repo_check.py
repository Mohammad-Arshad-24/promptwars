"""Check the public repository before using a scored attempt. Uses anonymous GitHub access."""
import json
import re
import sys
import urllib.request

def fetch(path):
    request = urllib.request.Request("https://api.github.com"+path, headers={"User-Agent":"LabLink-preflight", "Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)

def main(url):
    match = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)\.git",url)
    if not match:
        raise SystemExit("Expected a GitHub HTTPS repository URL ending in .git")
    base = "/repos/"+"/".join(match.groups())
    repo = fetch(base)
    branches = fetch(base+"/branches?per_page=2")
    assert not repo["private"], "Repository must be public"
    assert len(branches)==1, "Exactly one remote branch required"
    assert repo["size"] * 1024 < 10_000_000, "Repository size exceeds the briefing limit"
    print(f"PASS: public, one branch ({branches[0]['name']}), GitHub reports {repo['size']} KiB. URL: {url}")

if __name__=="__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "https://github.com/Mohammad-Arshad-24/promptwars.git")

