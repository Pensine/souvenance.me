"""The image's dependencies, read from pyproject.toml (a single source).

usage: python requirements.py <comma-separated extras> <transcription>
transcription: none | faster-whisper | whisperx
"""

import sys
import tomllib

project = tomllib.load(open("pyproject.toml", "rb"))["project"]
extras = [e.strip() for e in sys.argv[1].split(",") if e.strip()]
transcription = sys.argv[2] if len(sys.argv) > 2 else "none"

deps = list(project["dependencies"])
for extra in extras:
    deps += project["optional-dependencies"][extra]
if transcription == "faster-whisper":
    deps += project["optional-dependencies"]["transcription"]
elif transcription == "whisperx":
    deps += [d for d in project["optional-dependencies"]["local"]
             if d.startswith(("whisperx", "pyannote"))]
elif transcription != "none":
    sys.exit(f"unknown transcription: {transcription}")
print("\n".join(deps))
