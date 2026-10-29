"""Generate the native recording of each thought with the reference-voice model.

This is the only narration module that runs the voice model, so validation and review code
never loads the speech runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import mlx.core as mx
import numpy as np
from huggingface_hub import snapshot_download
from mlx_audio.audio_io import read, write
from mlx_audio.tts.utils import load_model
from mlx_audio.utils import load_audio

import filmkit.repository as repository
from filmkit.narration.run_on import cut_run_on
from filmkit.narration.thought_groups import (
    GROUP_POLICY,
    RetainedUtteranceError,
    child_receipt,
    child_request,
    join_quiet,
    retained_group,
)
from filmkit.narration.voice_model import (
    MLX_CACHE_LIMIT_BYTES,
    MODEL,
    MODEL_FILES,
    NATIVE_STREAM,
    REVISION,
    request_fingerprint,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class PlannedChild:
    """One thought's request and recording, with its receipt and PCM when already retained."""

    request: dict
    fingerprint: str
    wave: Path
    retained: tuple[dict, np.ndarray] | None

    @property
    def receipt(self) -> Path:
        return self.wave.with_suffix(".json")

    @property
    def request_file(self) -> Path:
        return self.wave.with_suffix(".request.json")


def load_voice_model():
    """Load the pinned reference-voice model from the local cache under its buffer bound."""
    local = snapshot_download(
        MODEL, revision=REVISION, allow_patterns=MODEL_FILES, local_files_only=True
    )
    mx.set_cache_limit(MLX_CACHE_LIMIT_BYTES)
    return load_model(local)


def synthesize(
    model, text: str, reference: Path, reference_text: str, settings: dict, seed: int
) -> tuple[np.ndarray, int]:
    """Narrate one text natively from a seed.

    Returns:
        The float samples and the number of chunks the model yielded.
    """
    mx.random.seed(seed)
    parts = [
        np.asarray(result.audio, dtype=np.float32)
        for result in _native_results(model, text, reference, reference_text, settings)
    ]
    return np.concatenate(parts), len(parts)


def _native_results(model, text: str, reference: Path, reference_text: str, settings: dict):
    """Yield native ICL results under the cast's declared sampling.

    mlx-audio 0.5.8 generate() raises any ICL repetition penalty below 1.5; at
    that floor the model ends many Chinese utterances inside the last syllable.
    A cast that declares the model's own default calls the same unmodified
    vendor ICL generator with that penalty.
    """
    penalty = settings.get("icl_repetition_penalty")
    if penalty is None:
        return model.generate(
            text=text,
            ref_audio=str(reference),
            ref_text=reference_text,
            lang_code=settings["language"],
            temperature=settings["temperature"],
            top_p=0.9,
            max_tokens=settings["max_tokens"],
            stream=NATIVE_STREAM,
            verbose=False,
        )
    # The vendor's own ICL generator is the only call that takes a penalty below its floor.
    return model._generate_icl(  # noqa: SLF001
        text=text,
        ref_audio=load_audio(str(reference), sample_rate=model.sample_rate),
        ref_text=reference_text,
        language=settings["language"],
        temperature=settings["temperature"],
        max_tokens=settings["max_tokens"],
        top_k=50,
        top_p=0.9,
        repetition_penalty=penalty,
        stream=NATIVE_STREAM,
    )


def generate_native_groups(
    model, plans: list[dict], path: Path, settings: dict
) -> tuple[np.ndarray, int, dict]:
    """Retain native complete-thought recordings and join them with measured added quiet.

    Every thought is checked before any is generated: a received one is reused, and an
    unresolved one refuses the whole recording before any effect.

    Returns:
        The joined PCM, the number of chunks the model yielded and the groups' receipt.
    """
    planned = [
        _planned_child(model, settings, thought, index, path)
        for index, thought in enumerate(plans, 1)
    ]
    path.with_suffix("").mkdir(parents=True, exist_ok=True)
    children = [child.retained or _record_child(model, child, settings) for child in planned]
    audio, joins, starts = _join([pcm for _, pcm in children], model.sample_rate)
    records = [
        {
            **child,
            "receipt": str(plan.receipt.relative_to(repository.ROOT)),
            "receipt_sha256": repository.sha(plan.receipt),
            "start_sample": start,
        }
        for (child, _), plan, start in zip(children, planned, starts, strict=True)
    ]
    groups = {
        "policy": GROUP_POLICY,
        "records": records,
        "joins": joins,
        "listening_accepted": False,
    }
    return audio, sum(child["native_chunks"] for child, _ in children), groups


def _planned_child(model, settings: dict, thought: dict, index: int, path: Path) -> PlannedChild:
    """Plan one thought: reuse its received recording, or refuse an unresolved one."""
    request = child_request(settings, thought, index)
    fingerprint = request_fingerprint(request)
    wave = path.with_suffix("") / f"{index:02d}-{fingerprint[:12]}.wav"
    planned = PlannedChild(request, fingerprint, wave, None)
    if wave.exists() and planned.receipt.exists():
        child = repository.read(planned.receipt)
        pcm, _ = retained_group(child, request, wave, repository.ROOT.resolve())
        if child["sample_rate"] != model.sample_rate:
            msg = "Retained utterance sample rate changed"
            raise RetainedUtteranceError(msg)
        return PlannedChild(request, fingerprint, wave, (child, pcm))
    if any(
        file.exists() or file.is_symlink() for file in (wave, planned.receipt, planned.request_file)
    ):
        msg = "Unresolved native utterance; inspect before replay"
        raise RetainedUtteranceError(msg)
    return planned


def _record_child(model, planned: PlannedChild, settings: dict) -> tuple[dict, np.ndarray]:
    """Record one thought, retain its recording and receipt, and return them with its PCM.

    A thought with a run-on is narrated on into it and kept up to its declared cut.
    """
    repository.write(planned.request_file, {"state": "started", "fingerprint": planned.fingerprint})
    run_on = planned.request.get("run_on")
    audio, chunks = synthesize(
        model,
        planned.request["spoken_text"] + (run_on["spoken_text"] if run_on else ""),
        repository.ROOT / settings["reference_audio"],
        settings["reference_text"],
        settings,
        planned.request["seed"],
    )
    native = len(audio)
    if run_on:
        audio = cut_run_on(audio, run_on["cut_sample"], model.sample_rate)
    if audio.ndim != 1 or not np.isfinite(audio).all() or len(audio) <= model.sample_rate:
        msg = "Invalid native utterance recording"
        raise RuntimeError(msg)
    write(str(planned.wave), audio, model.sample_rate)
    # Join retained PCM, rather than an unretained float precursor.
    pcm, rate = read(str(planned.wave), dtype="int16")
    child = child_receipt(
        planned.request,
        path=str(planned.wave.relative_to(repository.ROOT)),
        wav_sha256=repository.sha(planned.wave),
        frames=len(pcm),
        sample_rate=rate,
        native_chunks=chunks,
        native_frames=native if run_on else None,
    )
    repository.write(planned.receipt, child)
    repository.write(
        planned.request_file, {"state": "received", "fingerprint": planned.fingerprint}
    )
    return child, pcm


def _join(audios: list[np.ndarray], rate: int) -> tuple[np.ndarray, list[dict], list[int]]:
    """Join the thoughts with only added quiet.

    Returns:
        The joined PCM, the join after each thought but the last, and each thought's start.
    """
    pieces, joins, starts, cursor = [], [], [], 0
    for index, audio in enumerate(audios, 1):
        starts.append(cursor)
        pieces.append(audio)
        cursor += len(audio)
        if index < len(audios):
            native, added = join_quiet(audio, audios[index], rate)
            pieces.append(np.zeros(added, dtype=np.int16))
            joins.append(
                {
                    "after_group": index,
                    "source_sample": cursor,
                    "native_quiet_frames": native,
                    "added_quiet_frames": added,
                    "removed_samples": 0,
                    "listening_accepted": False,
                }
            )
            cursor += added
    return np.concatenate(pieces), joins, starts
