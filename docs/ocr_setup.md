# OCR setup (Step 4c): exact offline install, for the owner to run

Status: **prepared, nothing installed or downloaded by an agent.** The owner runs every command below in her own
PowerShell, from the repository root, and pastes the output back. After that, the agent checks every hash against
the "expected" column of the record table (§6) and fills in the "measured" column.

Versions and hashes were read from PyPI, Hugging Face and the Ollama library on 2026-10-04.

## 0. Layout and rules

- Readers (decision log, Oct 4):
  - **Reader 1: PaddleOCR.** PP-OCRv5 mobile on the laptop CPU; PaddleOCR-VL on the work GPU.
  - **Reader 2: GLM-OCR** (Z.ai, 0.9B, MIT, GLM-V architecture: a different family from Paddle), run locally
    through Ollama, **on number-bearing crops only**. We call the model itself. We do not use the `glmocr` SDK
    pipeline, because it embeds a Paddle layout model and would make reader 2 share reader 1's failure modes.
  - **Reader 3: TeleOCR or OvisOCR2** (Apache-2.0). GPU only, and only as a tie-breaker when readers 1 and 2
    disagree.
  - **Voting rule:** a number is accepted only when at least 2 readers agree exactly. Otherwise it is flagged.
  - **Free internal checks:** table totals must add up, and a number that appears in both the text and a table must
    match. Any mismatch flags the numbers involved.
- Models go in `models/ocr/<model name>/`. `models/` is git-ignored, so the hashes below are the record.
- OCR runs in its own venv, `.venv-ocr` (git-ignored by `.venv*/`). Paddle and PaddleX pull in a large dependency tree
  (OpenCV, shapely, pyclipper and others). Keeping that tree out of `.venv` protects the pinned pipeline/test
  environment. The pipeline calls OCR as a worker process.
- Wheels are downloaded into `wheelhouse\ocr\` (git-ignored by `wheelhouse/`). Then the venv installs with
  `--no-index`, the same pattern as `scripts/install_offline.ps1`.
- Network: only these download commands touch the network, and the owner runs them herself. Every OCR run after
  that is offline. The test in §2.4 proves it with `checks/egress_guard.py`.

## 1. Prerequisite for Step 4b (not OCR): pdfplumber + pypdfium2 in `.venv`

pdfplumber 0.11.10 requires `Pillow>=12.2`, and `.venv` pins Pillow 11.3.0, which the deck renderer is tested on.
So we pin **pdfplumber 0.11.9** (MIT, 2026-01-05; requires `pdfminer.six==20251230`, `Pillow>=9.1`,
`pypdfium2>=4.18`) and **pypdfium2 5.13.0** (Apache-2.0 / BSD-3-Clause, bundles PDFium).

```powershell
.venv\Scripts\python.exe -m pip download --only-binary=:all: --dest wheelhouse "pdfplumber==0.11.9" "pdfminer.six==20251230" "pypdfium2==5.13.0"; .venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse "pdfplumber==0.11.9" "pdfminer.six==20251230" "pypdfium2==5.13.0"; .venv\Scripts\python.exe -m pip check
```

Expected new packages: pdfplumber, pdfminer.six, pypdfium2, charset-normalizer, cryptography, and cffi/pycparser if
cryptography needs them. The agent then adds the pins to `requirements.txt` and `requirements.lock.txt`, and the
hashes to `wheelhouse/SHA256SUMS.txt`.

## 2. Reader 1: PaddleOCR (CPU, laptop)

### 2.1 Pins

| Package | Version | Licence | Note |
|---|---|---|---|
| `paddleocr` | 3.7.0 (2026-06-11) | Apache-2.0 | pulls `paddlex[ocr-core]>=3.7.0,<3.8.0` |
| `paddlepaddle` (CPU) | 3.3.1 | Apache-2.0 | cp311 win_amd64 wheel sha256 `9651888c3586e2da4e443a0ee7630b95afbf58e6fbfee6203e6975cb642e615b` |

For Ubuntu (production), the same pins apply. `paddlepaddle-3.3.1-cp311-cp311-manylinux1_x86_64.whl` has sha256
`bb22396233d807f6957d9c4a6a1edc76693fb589c4ee3d17caf7e39113ca4047`, and the cp312 wheel has
`9016fc497213e1101261684321fbb31ef5960019ef39cb07ded27bc70e2a9858`. Which Python version Ubuntu uses is still the
open packaging decision (HANDOFF, known risks).

### 2.2 Install (Windows, one command)

```powershell
py -3.11 -m venv .venv-ocr; .venv-ocr\Scripts\python.exe -m pip download --only-binary=:all: --dest wheelhouse\ocr "paddlepaddle==3.3.1" "paddleocr==3.7.0"; .venv-ocr\Scripts\python.exe -m pip install --no-index --find-links wheelhouse\ocr "paddlepaddle==3.3.1" "paddleocr==3.7.0"; .venv-ocr\Scripts\python.exe -m pip check; .venv-ocr\Scripts\python.exe -m pip freeze > wheelhouse\ocr\freeze.txt
```

If `--only-binary=:all:` stops on a package that has no wheel, paste the error and do not switch to a source build.
The agent will pick a pin that has a wheel.

Ubuntu equivalent, for later: `python3 -m venv .venv-ocr && .venv-ocr/bin/pip download --only-binary=:all: --dest
wheelhouse/ocr paddlepaddle==3.3.1 paddleocr==3.7.0 && .venv-ocr/bin/pip install --no-index --find-links
wheelhouse/ocr paddlepaddle==3.3.1 paddleocr==3.7.0`. Windows wheels do not install on Linux (audit F-04), so the
download must run on Linux or with `--platform manylinux1_x86_64 --python-version 3.12`.

### 2.3 Models: PP-OCRv5 mobile det + rec, pinned to a Hugging Face commit

| Model | HF repo @ commit | Big file | Bytes | sha256 (HF LFS oid) |
|---|---|---|---|---|
| `PP-OCRv5_mobile_det` | `PaddlePaddle/PP-OCRv5_mobile_det` @ `0d63e78e2b680928f6b1747d76a08db6e645efb7` | `inference.pdiparams` | 4,692,937 | `afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b` |
| `PP-OCRv5_mobile_rec` | `PaddlePaddle/PP-OCRv5_mobile_rec` @ `682f20538d8c086cb2128e5cfac775e6c4904e85` | `inference.pdiparams` | 16,458,665 | `2460da90875937c94db97eba74ae3d9e5d4c4c57c42f1f41531c09a26bcc771a` |

Each model folder needs `inference.json`, `inference.pdiparams`, `inference.yml` and `config.json`. The small files
are not LFS objects. Their sha256 is measured after download and recorded in §6.

```powershell
$m = @{ "PP-OCRv5_mobile_det" = "0d63e78e2b680928f6b1747d76a08db6e645efb7"; "PP-OCRv5_mobile_rec" = "682f20538d8c086cb2128e5cfac775e6c4904e85" }; foreach ($name in $m.Keys) { $dir = "models\ocr\$name"; New-Item -ItemType Directory -Force $dir | Out-Null; foreach ($f in "inference.json","inference.pdiparams","inference.yml","config.json") { Invoke-WebRequest -UseBasicParsing -Uri "https://huggingface.co/PaddlePaddle/$name/resolve/$($m[$name])/$f" -OutFile "$dir\$f" } }; Get-ChildItem models\ocr -Recurse -File | Get-FileHash -Algorithm SHA256 | Format-Table Hash, Path -AutoSize
```

### 2.4 How Matn calls it (Step 4c code; recorded here so the settings are reviewed now)

```python
import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"  # set before importing paddleocr: no hoster check
from paddleocr import PaddleOCR

ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv5_mobile_det",
    text_detection_model_dir="models/ocr/PP-OCRv5_mobile_det",
    text_recognition_model_name="PP-OCRv5_mobile_rec",
    text_recognition_model_dir="models/ocr/PP-OCRv5_mobile_rec",
    use_doc_orientation_classify=False,  # no orientation model: pages are rendered upright by pypdfium2
    use_doc_unwarping=False,             # no UVDoc model: scans are flat, unwarping can move characters
    use_textline_orientation=False,      # no textline classifier
    device="cpu",
)
```

- Both the name and the dir are set for every model that is used. The three switched-off stages load no model, so
  nothing else can be fetched.
- Offline proof: `tests/test_ocr_offline.py` (Step 4c) runs this setup on a generated image inside
  `checks.egress_guard.block_egress()`. If any code path tries to reach a model host, the test fails with
  `EgressBlocked`. It skips with a stated reason when `.venv-ocr` or the model folders are absent.

### 2.5 Later, on the work GPU: PaddleOCR-VL

The candidate is `PaddlePaddle/PaddleOCR-VL-1.6` @ `c5630abae1d940eafe0697512a0325494b02ab42` (Apache-2.0).
`model.safetensors` is 1,917,255,968 bytes, sha256 `85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db`.
`tokenizer.json` has sha256 `c8a215a59183d0d0781adc33bacd3ce6162716f7fd568fb30234a74d69803a7d`, and
`tokenizer.model` has `34ef7db83df785924fb83d7b887b6e822a031c56e15cff40aaf9b982988180df`. It needs `paddlepaddle-gpu`
and a `paddleocr` release that lists VL-1.6. Confirm both on the GPU machine before downloading. Do not download it
now.

## 3. Reader 2: GLM-OCR through Ollama (strong, independent, MIT)

The laptop already has Ollama **0.35.1**.

| Tag | Size | Digest (ollama.com) | Choice |
|---|---|---|---|
| `glm-ocr:bf16` | 2.2 GB | `6effedd0dc8a` (same blob as `glm-ocr:latest`) | **use this**: full precision. A quantized model is not used to read digits. |
| `glm-ocr:q8_0` | 1.6 GB | `2a5a0f1a9301` | not used |

Upstream weights: `zai-org/GLM-OCR` @ `2e85a62840ccac27daa451df36c736c4636b8628`, MIT.

### 3.1 Pull once (owner)

```powershell
ollama pull glm-ocr:bf16; ollama list; ollama show glm-ocr:bf16 --modelfile | Select-String "^FROM"
```

`ollama list` must show ID `6effedd0dc8a`. The `FROM` line gives the full `sha256-…` blob digest, which goes in §6.
If the ID differs, stop: the tag was re-published, and the new one needs its own review.

### 3.2 Calling it on a crop

The prompt is the model's own task prefix, `Text Recognition:`. Matn sends **one crop around each number-bearing
line or table cell**, never a whole page:

- small crops keep the image-token count low;
- a crop gives the model no surrounding sentence to "correct" a digit from.

`num_ctx` must hold the image tokens plus the answer. Ollama's default context is too small for large images, so we
set **`num_ctx: 16384`** (a full 300-DPI page would need more; crops need far less). `temperature: 0` and a fixed
`seed` make the reading repeatable.

Manual check (PowerShell, owner, optional). `crop.png` is any small image of printed numbers:

```powershell
$img = [Convert]::ToBase64String([IO.File]::ReadAllBytes("crop.png")); @{ model = "glm-ocr:bf16"; prompt = "Text Recognition:"; images = @($img); stream = $false; options = @{ num_ctx = 16384; temperature = 0; seed = 0 } } | ConvertTo-Json -Depth 4 | Set-Content -Encoding ascii glm_body.json; curl.exe --noproxy "*" -s http://127.0.0.1:11434/api/generate -H "Content-Type: application/json" -d "@glm_body.json"
```

(`curl.exe --noproxy "*"` is used because Windows PowerShell 5.1's `Invoke-RestMethod` has no `-NoProxy` switch.)

In Matn code (Step 4c), the same request goes through a **no-proxy** `urllib` opener to `127.0.0.1` only (audit F-03:
the default opener follows HTTP_PROXY, so the request could leave the machine through a proxy). No new Python
dependency is needed.

## 4. Reader 3 (GPU only, tie-breaker; download later, not now)

Both are Hugging Face Transformers models. TeleOCR ships its own `modeling_naviocr.py` (`trust_remote_code`). That
file is code from the internet, so the agent reviews it before it ever runs, and its sha256 is pinned like the
weights.

| Model | Repo @ commit | Licence | `model.safetensors` bytes | sha256 |
|---|---|---|---|---|
| TeleOCR (~1.2B) | `XingChen-AGI/TeleOCR` @ `e92585356c0d0b7b7a65938f3da035c6593cc9a6` | Apache-2.0 | 2,830,223,488 | `9817b18041bd96403f75e38a33b28ed0cd5fb2641f67eead673afabd3c408109` |
| OvisOCR2 (0.8B, from Qwen3.5-0.8B) | `ATH-MaaS/OvisOCR2` @ `1fc9221b7823a371d6e97f92d527cc847e24e107` | Apache-2.0 | 1,706,030,496 | `9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009` |

Download command for the GPU machine. It is pinned to the commit, and the hash is checked right after:

```powershell
$repos = @{ "TeleOCR" = @("XingChen-AGI/TeleOCR", "e92585356c0d0b7b7a65938f3da035c6593cc9a6", @("config.json","generation_config.json","chat_template.jinja","added_tokens.json","special_tokens_map.json","tokenizer.json","tokenizer_config.json","vocab.json","merges.txt","preprocessor_config.json","video_preprocessor_config.json","modeling_naviocr.py","model.safetensors")); "OvisOCR2" = @("ATH-MaaS/OvisOCR2", "1fc9221b7823a371d6e97f92d527cc847e24e107", @("config.json","chat_template.jinja","tokenizer.json","tokenizer_config.json","vocab.json","merges.txt","preprocessor_config.json","video_preprocessor_config.json","LICENSE","model.safetensors")) }; foreach ($k in $repos.Keys) { $r = $repos[$k]; $dir = "models\ocr\$k"; New-Item -ItemType Directory -Force $dir | Out-Null; foreach ($f in $r[2]) { Invoke-WebRequest -UseBasicParsing -Uri "https://huggingface.co/$($r[0])/resolve/$($r[1])/$f" -OutFile "$dir\$f" } }; Get-FileHash models\ocr\TeleOCR\model.safetensors, models\ocr\OvisOCR2\model.safetensors -Algorithm SHA256 | Format-Table Hash, Path -AutoSize
```

Which of the two becomes reader 3 is decided on the GPU by the same reading benchmark: whichever has the lower
silent-error rate on number crops, with false alarms as the tie-break.

## 5. What the gate measures (Step 4c)

On the synthetic scans (`eval/reading/synthetic/`), with exact ground truth:

- the agreement and disagreement rates between reader 1 and reader 2 on number tokens;
- of the disagreements, how many reader 1 actually had right. Those flags were unnecessary, so this is the
  **false-alarm rate**;
- **silent errors: must stay 0.** A silent error is a wrong number that is accepted or not flagged, for example
  when both readers agree on the same wrong digit.

## 6. Record (expected values from the hosts; measured values filled in after download)

| Item | Version / tag / commit | File | Expected sha256 | Measured sha256 |
|---|---|---|---|---|
| paddlepaddle | 3.3.1 cp311 win_amd64 | wheel | `9651888c3586e2da4e443a0ee7630b95afbf58e6fbfee6203e6975cb642e615b` | |
| paddleocr | 3.7.0 | wheel | (from `pip download`) | |
| PP-OCRv5_mobile_det | `0d63e78e…` | inference.pdiparams | `afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b` | |
| PP-OCRv5_mobile_det | `0d63e78e…` | inference.json / .yml / config.json | (measured) | |
| PP-OCRv5_mobile_rec | `682f2053…` | inference.pdiparams | `2460da90875937c94db97eba74ae3d9e5d4c4c57c42f1f41531c09a26bcc771a` | |
| PP-OCRv5_mobile_rec | `682f2053…` | inference.json / .yml / config.json | (measured) | |
| GLM-OCR | `glm-ocr:bf16`, ID `6effedd0dc8a` | Ollama blob (`FROM` line) | (full digest from `ollama show`) | |
| PaddleOCR-VL-1.6 | `c5630aba…` | model.safetensors | `85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db` | GPU, later |
| TeleOCR | `e9258535…` | model.safetensors | `9817b18041bd96403f75e38a33b28ed0cd5fb2641f67eead673afabd3c408109` | GPU, later |
| OvisOCR2 | `1fc9221b…` | model.safetensors | `9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009` | GPU, later |
