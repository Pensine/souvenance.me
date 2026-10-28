"""Speaker identification (phase 2) — pyannote + ECAPA-TDNN voiceprints.

Third-party rule (§8): channel metadata (the forwarder of the message)
ALWAYS takes precedence over ML; enrolling a voiceprint is an explicit act
(scripts/enroll_speaker.py). Optional building blocks: without
speechbrain/pyannote installed, everything degrades gracefully (speakers 'unknown').
"""

from pathlib import Path

EMBED_DIM = 192  # ECAPA-TDNN (speechbrain spkrec-ecapa-voxceleb)


def compute_voiceprint(wav_path: Path) -> list[float]:
    """Voiceprint of an audio sample (mono 16 kHz preferably)."""
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb")
    signal, sr = torchaudio.load(str(wav_path))
    if sr != 16000:
        signal = torchaudio.functional.resample(signal, sr, 16000)
    emb = classifier.encode_batch(signal).squeeze()
    return [float(x) for x in emb]


def identify_segments(conn, wav_path: Path, *, sender_entity_id: int | None = None,
                      threshold: float = 0.35) -> list[dict] | None:
    """Diarize the file and identify each segment.

    If `sender_entity_id` is provided (channel metadata — e.g. the sender of a
    forwarded WhatsApp voice note), it is assigned outright to the dominant
    speaker: the channel takes precedence over ML. Returns None if pyannote is absent."""
    # With no enrolled voiceprint and no known sender, diarization cannot
    # name anyone: no point loading pyannote (several hundred MB more in a
    # nightly cycle that shares the server).
    if sender_entity_id is None and not conn.execute(
            "SELECT 1 FROM voiceprints LIMIT 1").fetchone():
        return None
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        return None

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    diarization = pipeline(str(wav_path))

    # Group segments by pyannote speaker
    turns: dict[str, list[tuple[float, float]]] = {}
    for turn, _, label in diarization.itertracks(yield_label=True):
        turns.setdefault(label, []).append((turn.start, turn.end))

    dominant = max(turns, key=lambda k: sum(e - s for s, e in turns[k])) \
        if turns else None
    results = []
    for label, segments in turns.items():
        entity_id = None
        if label == dominant and sender_entity_id is not None:
            entity_id = sender_entity_id       # the channel takes precedence over ML
        else:
            entity_id = _match_voiceprint(conn, wav_path, segments, threshold)
        results.extend(
            {"start": round(s, 2), "end": round(e, 2),
             "entity_id": entity_id, "diarization_label": label}
            for s, e in segments
        )
    return sorted(results, key=lambda r: r["start"])


def _match_voiceprint(conn, wav_path: Path, segments: list[tuple[float, float]],
                      threshold: float) -> int | None:
    """Speaker voiceprint over their segments → nearest neighbor via pgvector."""
    try:
        import torchaudio
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError:
        return None
    signal, sr = torchaudio.load(str(wav_path))
    if sr != 16000:
        signal = torchaudio.functional.resample(signal, sr, 16000)
        sr = 16000
    # Concatenate up to 30 s of this speaker's segments
    import torch
    chunks, total = [], 0.0
    for s, e in segments:
        chunks.append(signal[:, int(s * sr):int(e * sr)])
        total += e - s
        if total > 30:
            break
    if not chunks:
        return None
    emb = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb"
    ).encode_batch(torch.cat(chunks, dim=1)).squeeze()
    vector = [float(x) for x in emb]

    row = conn.execute(
        """
        SELECT entity_id, embedding <=> %s::vector AS distance
        FROM voiceprints ORDER BY distance LIMIT 1
        """,
        (str(vector),),
    ).fetchone()
    if row and row["distance"] is not None and row["distance"] < threshold:
        return row["entity_id"]
    return None
