"""Binary rendering of deposits: text files, neutral photos, PDFs, voice memos.

Photos are NON-FIGURATIVE on purpose: seeded colour fields and shapes, with
the date and GPS position written into EXIF. They never pretend to show an
event, so any memory describing what a photo "shows" is an invention by
construction (trap kind `photo_content`).

Voice memos are synthesised locally through a separate Python environment
(`--tts-python`), so the generator itself keeps zero heavy dependencies.
The default engine is Chatterbox (MIT), cloning five public-domain LibriVox
reference clips; Piper (five public-domain voices) is kept as a fallback
(`--tts-engine piper`). See SPEC sections 3.3 and 9. Light background noise
and a random lead-in are added.
Audio is NOT guaranteed bit-identical across machines; the manifest records
a SHA-256 of every file so a published release can be checked.
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .deposits import Deposit

HERE = Path(__file__).resolve().parent


# --- photos ----------------------------------------------------------------

def _dms(x: float) -> tuple:
    from PIL.TiffImagePlugin import IFDRational

    x = abs(x)
    d = int(x)
    m = int((x - d) * 60)
    s = round(((x - d) * 60 - m) * 60 * 100)
    return (IFDRational(d, 1), IFDRational(m, 1), IFDRational(s, 100))


def render_photo(d: Deposit, path: Path, seed: int) -> None:
    from PIL import Image, ImageDraw

    r = random.Random(f"{seed}:{d.id}")
    w, h = 960, 720
    base = tuple(r.randint(40, 215) for _ in range(3))
    img = Image.new("RGB", (w, h), base)
    draw = ImageDraw.Draw(img)
    for _ in range(r.randint(4, 9)):  # abstract colour fields, no figuration
        c = tuple(min(255, max(0, b + r.randint(-60, 60))) for b in base)
        x0, y0 = r.randint(-200, w), r.randint(-200, h)
        x1, y1 = x0 + r.randint(120, 600), y0 + r.randint(120, 500)
        (draw.ellipse if r.random() < 0.5 else draw.rectangle)((x0, y0, x1, y1), fill=c)
    exif = img.getexif()
    dt = datetime.fromisoformat(d.created_at).strftime("%Y:%m:%d %H:%M:%S")
    exif[0x0132] = dt                      # DateTime
    exif[0x010E] = "SOURCED synthetic photo (non-figurative)"  # ImageDescription
    exif[0x0131] = "sourced-generator"     # Software
    sub = exif.get_ifd(0x8769)             # Exif IFD
    sub[0x9003] = dt                       # DateTimeOriginal
    gps = exif.get_ifd(0x8825)             # GPS IFD
    lat, lon = d.meta["lat"], d.meta["lon"]
    gps[1], gps[2] = ("N" if lat >= 0 else "S"), _dms(lat)
    gps[3], gps[4] = ("E" if lon >= 0 else "W"), _dms(lon)
    img.save(path, "JPEG", quality=82, exif=exif)


def read_photo_exif(path: Path) -> dict:
    """Round-trip check used by the tests: date and decimal GPS from a JPEG."""
    from PIL import Image

    ex = Image.open(path).getexif()
    gps = ex.get_ifd(0x8825)

    def dec(v, ref):
        x = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        return -x if ref in ("S", "W") else x
    return {"datetime": ex.get_ifd(0x8769).get(0x9003),
            "lat": dec(gps[2], gps[1]), "lon": dec(gps[4], gps[3])}


# --- PDF -------------------------------------------------------------------

def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_pdf(text: str, path: Path) -> None:
    """A minimal, valid one-page PDF (Helvetica, one line per text line).
    Written by hand to avoid a dependency; text stays extractable."""
    lines = text.split("\n")
    ops = ["BT", "/F1 11 Tf", "14 TL", "72 760 Td"]
    for i, line in enumerate(lines):
        if i == 0:
            ops += ["/F1 14 Tf", f"({_pdf_escape(line)}) Tj", "/F1 11 Tf", "T*"]
        else:
            ops += [f"({_pdf_escape(line.encode('latin-1', 'replace').decode('latin-1'))}) Tj",
                    "T*"]
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
            .encode())
    path.write_bytes(bytes(out))


# --- voice -----------------------------------------------------------------

def render_voices(jobs: list[dict], tts_python: str, workdir: Path,
                  engine: str = "chatterbox", device: str = "cpu") -> None:
    """jobs: [{"text", "voice", "out", "seed"}]. Runs the TTS worker once for
    all jobs (the model and each voice loaded once), then compresses to AAC
    with ffmpeg."""
    if not jobs:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=workdir) as fh:
        json.dump(jobs, fh)
        job_file = fh.name
    subprocess.run([tts_python, str(HERE / "tts_worker.py"), "--engine", engine,
                    "--device", device, job_file], check=True)
    for j in jobs:
        wav = Path(j["out"]).with_suffix(".wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac",
                        "-b:a", "48k", "-map_metadata", "-1", "-fflags", "+bitexact",
                        "-flags:a", "+bitexact", j["out"]], check=True)
        wav.unlink()
    Path(job_file).unlink()


# --- orchestration ---------------------------------------------------------

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_all(deposits: list[Deposit], outdir: Path, seed: int,
               tts_python: str | None, tts_engine: str = "chatterbox",
               tts_device: str = "cpu") -> dict:
    """Writes every deposit file under outdir; returns {deposit id: sha256}.
    Without `tts_python`, voice deposits fall back to their transcript (.txt)
    and the manifest says so."""
    (outdir / "deposits").mkdir(parents=True, exist_ok=True)
    jobs = []
    for d in deposits:
        p = outdir / d.file
        if d.kind in ("note", "message", "message_in"):
            p.write_text(d.text + "\n", encoding="utf-8")
        elif d.kind == "photo":
            render_photo(d, p, seed)
        elif d.kind == "document":
            render_pdf(d.text, p)
        elif d.kind in ("voice", "voice_in"):
            if tts_python:
                jobs.append({"text": d.text, "voice": d.meta.get("voice", "female_a"),
                             "out": str(p), "seed": f"{seed}:{d.id}"})
            else:
                d.file = d.file.rsplit(".", 1)[0] + ".transcript.txt"
                d.meta["audio"] = "not rendered (no --tts-python)"
                (outdir / d.file).write_text(d.text + "\n", encoding="utf-8")
    if tts_python:
        render_voices(jobs, tts_python, outdir, tts_engine, tts_device)
    return {d.id: sha256(outdir / d.file) for d in deposits}
