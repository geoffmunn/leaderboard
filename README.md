# What is this?

This is a Python script that benchmarks quantized models using `llama.cpp`'s `llama-cli`, focusing on real-world user experience (speed, memory, responsiveness) on modest hardware like Raspberry Pi or laptops. It runs a representative set of prompts, captures key metrics, and maintains a persistent leaderboard in JSON format.

## Key Features:

1. **Real-World Metrics**:
   - **Tokens/sec**: Primary speed metric (averaged over 8 diverse prompts)
   - **Peak RAM Usage**: Critical for low-memory devices (uses `psutil` if available)
   - **File Size**: Model disk footprint
   - **Perplexity** (optional): Quality proxy via `--ppl`

2. **Hardware-Aware Defaults**:
   - Auto-detects CPU threads (defaults to 4 or CPU count)
   - Configurable context size, GPU layers, and mlock
   - Optimized for Raspberry Pi/laptops (modest defaults)

3. **Diverse Prompt Set**:
   - Covers explanation, coding, translation, math, summarization
   - Tests real-world responsiveness across tasks

4. **Persistent Leaderboard**:
   - Saves results to `leaderboard.json` (JSON format)
   - Avoids duplicate entries
   - Sorts by performance (tokens/sec)

5. **Error Resilience**:
   - Handles failed runs gracefully
   - Falls back if `psutil` isn't installed (memory = N/A)

## Usage:

1. **Build llama.cpp** (required):
   ```bash
   git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
   make -j && pip install -r requirements.txt
   ```

2. **Run benchmark**:
   ```bash
   # Basic usage (uses defaults suitable for Raspberry Pi)
   python3 benchmark.py models/your-model.Q5_K_M.gguf

   # With GPU offload (adjust layers for your VRAM)
   python3 benchmark.py models/model.gguf --gpu-layers 20

   # Include perplexity score
   python3 benchmark.py models/model.gguf --ppl

   # Custom prompts
   python3 benchmark.py model.gguf --prompts "What is AI?" "Explain photosynthesis"
   ```

3. **View results**:
   - Check `leaderboard.json` for machine-readable data
   - Human-readable summary printed after each run

## Notes for Low-End Hardware:

- **Raspberry Pi**: Reduce `--threads` to 2-4, `--ctx-size` to 1024-2048
- **Memory-constrained systems**: Use `--mlock` to prevent swapping
- **Slow storage**: Copy models to RAM disk (`/tmp`) before benchmarking
- **Disable PPL**: Perplexity calculation is slow; skip with `--no-ppl`

The script prioritizes **real user experience**—measuring how quickly a model responds during actual usage rather than synthetic benchmarks. This aligns with your focus on practical quantization tradeoffs (speed vs. quality vs. size).

It **DOES NOT** test for the quality of the answer, highly compressed models might be very fast but return rubbish results. The quality of a model is not part of this benchmarking tool.

## GitHub Uploads

If you are running this on your own computer and want to upload the results, you'll need to set up a SSH Key.

First, run this:

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

Then add the provided key details to your GitHub account:

```[GitHub → Settings → SSH Keys](https://github.com/settings/keys)```

And then convert your local repository to use SSH keys (if you haven't already done this) - make sure you change the username and repository name.

```bash
git remote set-url origin git@github.com:yourname/yourrepo.git
```
