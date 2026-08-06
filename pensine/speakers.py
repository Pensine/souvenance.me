"""Identification des locuteurs (phase 2) — pyannote + empreintes ECAPA-TDNN.

Règle des tiers (§8) : les métadonnées du canal (expéditeur du transfert)
priment TOUJOURS sur le ML ; l'enrôlement d'une empreinte est un acte
explicite (scripts/enroll_speaker.py). Briques optionnelles : sans
speechbrain/pyannote installés, tout dégrade proprement (locuteurs 'unknown').
"""

from pathlib import Path

EMBED_DIM = 192  # ECAPA-TDNN (speechbrain spkrec-ecapa-voxceleb)


def compute_voiceprint(wav_path: Path) -> list[float]:
    """Empreinte d'un échantillon audio (mono 16 kHz de préférence)."""
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
    """Diarise le fichier et identifie chaque segment.

    Si `sender_entity_id` est fourni (métadonnée du canal — ex. expéditeur
    d'un vocal WhatsApp transféré), il est attribué d'office au locuteur
    dominant : le canal prime sur le ML. Retourne None si pyannote absent."""
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        return None

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    diarization = pipeline(str(wav_path))

    # Regroupe les segments par locuteur pyannote
    turns: dict[str, list[tuple[float, float]]] = {}
    for turn, _, label in diarization.itertracks(yield_label=True):
        turns.setdefault(label, []).append((turn.start, turn.end))

    dominant = max(turns, key=lambda k: sum(e - s for s, e in turns[k])) \
        if turns else None
    results = []
    for label, segments in turns.items():
        entity_id = None
        if label == dominant and sender_entity_id is not None:
            entity_id = sender_entity_id       # le canal prime sur le ML
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
    """Empreinte du locuteur sur ses segments → plus proche voisin pgvector."""
    try:
        import torchaudio
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError:
        return None
    signal, sr = torchaudio.load(str(wav_path))
    if sr != 16000:
        signal = torchaudio.functional.resample(signal, sr, 16000)
        sr = 16000
    # Concatène jusqu'à 30 s des segments de ce locuteur
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
