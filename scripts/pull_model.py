"""Pull a real local model through Ollama, without credentials or cloud inference."""

import argparse
import json
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="qwen3:1.7b")
args = parser.parse_args()
request = urllib.request.Request(
    "http://127.0.0.1:11434/api/pull",
    method="POST",
    data=json.dumps({"model": args.model}).encode(),
    headers={"Content-Type": "application/json"},
)
last = ""
with urllib.request.urlopen(request, timeout=1800) as response:
    for line in response:
        event = json.loads(line)
        if "error" in event:
            raise RuntimeError(event["error"])
        status = event["status"]
        if event.get("total"):
            status += " " + str(int(event.get("completed", 0) / event["total"] * 10) * 10) + "%"
        if status != last:
            print(status, flush=True)
            last = status
