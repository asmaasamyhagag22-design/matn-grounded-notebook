"""Standalone CPU scoring sidecar; invoke with an isolated interpreter only."""

if __name__ != "__main__":
    raise ImportError("Reranker sidecar is standalone, never imported by the main suite")

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if Path(sys.prefix).resolve() in {ROOT / ".venv", Path(sys.base_prefix).resolve()}:
    raise RuntimeError("An isolated virtual environment is required")
sys.path.insert(0, str(ROOT))
from checks.egress_guard import block_egress


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                                    allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cost", type=Path, required=True)
    args = parser.parse_args()
    settings_path = ROOT / "eval/reranker_settings.json"
    settings = json.loads(settings_path.read_text())
    for name, version in settings["installed_versions"].items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError(f"Unpinned package: {name}")
    if sha(args.input) != args.input_sha256:
        raise RuntimeError("Input SHA mismatch")
    for name, metadata in settings["model_files"].items():
        if sha(args.model_path / name) != metadata["sha256"]:
            raise RuntimeError(f"Model artifact SHA mismatch: {name}")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    with block_egress():
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(settings["cpu_threads"])
        torch.set_num_interop_threads(1)
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        started = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(
            args.model_path, padding_side="left", local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            args.model_path, local_files_only=True).eval()
        if model.device.type != "cpu":
            raise RuntimeError("CPU scoring required")
        load_seconds = time.perf_counter() - started
        token_false_id = tokenizer.convert_tokens_to_ids("no")
        token_true_id = tokenizer.convert_tokens_to_ids("yes")
        if token_false_id == token_true_id or tokenizer.unk_token_id in (
                token_false_id, token_true_id):
            raise RuntimeError("Invalid yes/no token IDs")
        prefix_tokens = tokenizer.encode(settings["prefix"], add_special_tokens=False)
        suffix_tokens = tokenizer.encode(settings["suffix"], add_special_tokens=False)
        max_length = settings["max_length"]
        results, costs = [], []
        for query in json.loads(args.input.read_text())["queries"]:
            start = time.perf_counter()
            passages = query["passages"]
            scores = []
            for offset in range(0, len(passages), settings["batch_size"]):
                batch = passages[offset:offset + settings["batch_size"]]
                pairs = ["<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}".format(
                    instruction=settings["instruction"], query=query["query"], doc=p["text"])
                    for p in batch]
                inputs = tokenizer(
                    pairs, padding=False, truncation="longest_first",
                    return_attention_mask=False,
                    max_length=max_length - len(prefix_tokens) - len(suffix_tokens))
                for i, ele in enumerate(inputs["input_ids"]):
                    inputs["input_ids"][i] = prefix_tokens + ele + suffix_tokens
                inputs = tokenizer.pad(inputs, padding=True, return_tensors="pt",
                                       max_length=max_length)
                for key in inputs:
                    inputs[key] = inputs[key].to(model.device)
                with torch.no_grad():
                    batch_scores = model(**inputs).logits[:, -1, :]
                    true_vector = batch_scores[:, token_true_id]
                    false_vector = batch_scores[:, token_false_id]
                    batch_scores = torch.stack([false_vector, true_vector], dim=1)
                    batch_scores = torch.nn.functional.log_softmax(batch_scores, dim=1)
                    scores.extend(batch_scores[:, 1].exp().tolist())
            costs.append({"id": query["id"], "passages": len(passages),
                          "seconds": time.perf_counter() - start})
            results.append({"id": query["id"], "scores": [
                {"id": p["id"], "score": score} for p, score in zip(passages, scores)]})
        write(args.output, {"input_sha256": args.input_sha256,
                            "configuration_sha256": sha(settings_path),
                            "model_revision": settings["model_revision"],
                            "yes_token_id": token_true_id, "no_token_id": token_false_id,
                            "queries": results})
        write(args.cost, {"load_seconds": load_seconds, "queries": costs,
                          "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          "scope": "sidecar process; CPU, no generation; cold first scoring query"})


main()
