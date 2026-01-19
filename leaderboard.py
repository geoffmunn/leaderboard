#!/usr/bin/env python3
"""
Quantized Model Leaderboard for llama.cpp — Non-Interactive Benchmark

Features:
- Tokens/sec from TTY output
- Peak RAM usage (runtime)
- System RAM (GB) as separate column
- Perplexity via --ppl (temporary file method)
- Accurate parameter count via GGUF metadata (new API)
- Hardware detection (Raspberry Pi, CPU, OS)
- Saves to ./docs/leaderboard.json
- Includes "Date Checked" timestamp
- Optional GitHub auto-upload
- Relaxed outlier detection (keeps normal variations, catches broken quants)
"""

import argparse
import json
import os
import sys
import time
import pty
import select
import subprocess
import platform
import re
import tempfile
from datetime import datetime

# Try to import optional dependencies
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: 'psutil' not installed. Peak memory will not be recorded.", file=sys.stderr)

try:
    from gguf import GGUFReader
    GGUF_AVAILABLE = True
except ImportError:
    GGUF_AVAILABLE = False
    print("Warning: 'gguf' not installed. Using filename-based parameter detection.", file=sys.stderr)

# Representative prompts
PROMPTS = [
    "Explain quantum computing in simple terms.",
    "Write a Python function to calculate Fibonacci numbers recursively.",
    "Summarize the causes of the French Revolution.",
    "What are the health benefits of regular exercise?",
    "Translate this sentence to French: 'The weather is beautiful today.'",
    "Solve for x: 2x + 5 = 15",
    "Describe the water cycle in 3 sentences.",
    "List 5 tips for improving sleep quality."
]

# Simple PPL prompt (single sentence works best)
PPL_PROMPT = "The quick brown fox jumps over the lazy dog."

def get_model_size_mb(model_path: str) -> float:
    return os.path.getsize(model_path) / (1024 * 1024)

# def extract_parameters_from_gguf(model_path: str) -> str:
#     """Extract parameter count from GGUF metadata (new API)."""
#     if not GGUF_AVAILABLE:
#         return None
#     try:
#         reader = GGUFReader(model_path)
#         if "general.parameter_count" in reader.fields:
#             count = reader.fields["general.parameter_count"].parts[-1]
#             if isinstance(count, int):
#                 if count >= 10**9:
#                     return f"{count / 1e9:.1f}B"
#                 elif count >= 10**6:
#                     return f"{count / 1e6:.1f}M"
#                 else:
#                     return f"{count}"
#         return None
#     except Exception as e:
#         print(f"GGUF metadata read error: {e}", file=sys.stderr)
#         return None
    
def extract_parameters_from_name(model_name: str) -> str:
    """Fallback: extract from filename."""
    base_name = os.path.splitext(model_name)[0]
    match = re.search(r'(\d+\.?\d*[BbMm])', base_name)
    if match:
        return match.group(1).upper()
    if any(x in base_name for x in ['0.5', '0.6', 'tiny']):
        return "0.6B"
    elif '1.5' in base_name:
        return "1.5B"
    elif '1.7' in base_name:
        return "1.7B"
    elif '3' in base_name and not any(x in base_name for x in ['1.7', '7', '13', '34']):
        return "3B"
    elif '7' in base_name and not any(x in base_name for x in ['1.7', '17', '70']):
        return "7B"
    elif '13' in base_name:
        return "13B"
    elif '34' in base_name:
        return "34B"
    return "Unknown"

def extract_huggingface_repo_from_gguf(model_path: str) -> str:
    """Extract HuggingFace repository URL from GGUF metadata if available."""
    if not GGUF_AVAILABLE:
        return None
    try:
        reader = GGUFReader(model_path)
        # Check common field names that might contain HuggingFace repo info
        possible_fields = [
            "general.source_url",
            "general.source",
            "general.url",
            "general.repository",
            "general.huggingface_repo",
            "custom.source_url",
            "custom.huggingface_repo",
        ]
        
        for field_name in possible_fields:
            if field_name in reader.fields:
                value = reader.fields[field_name].parts[-1]
                # Convert bytes to string if needed
                if isinstance(value, bytes):
                    value = value.decode('utf-8', errors='ignore')
                if isinstance(value, str):
                    value = value.strip()
                    # Check if it looks like a HuggingFace URL
                    if "huggingface.co" in value.lower():
                        return value
                    # If it's a repo name (user/repo format), construct the URL
                    elif "/" in value and not value.startswith("http"):
                        return f"https://huggingface.co/{value}"
        
        return None
    except Exception as e:
        # Silently fail - this is optional metadata
        return None

def extract_parameters_from_name(model_name: str) -> str:
    """Fallback: extract from filename."""
    base_name = os.path.splitext(model_name)[0]
    match = re.search(r'(\d+\.?\d*[BbMm])', base_name)
    if match:
        return match.group(1).upper()
    if any(x in base_name for x in ['0.5', '0.6', 'tiny']):
        return "0.6B"
    elif '1.5' in base_name:
        return "1.5B"
    elif '3' in base_name and not any(x in base_name for x in ['7', '13', '34']):
        return "3B"
    elif '7' in base_name:
        return "7B"
    elif '13' in base_name:
        return "13B"
    elif '34' in base_name:
        return "34B"
    return "Unknown"

def detect_hardware_info():
    """Detect hardware info with separate RAM value."""
    try:
        device = "Unknown Device"
        machine = platform.machine().lower()
        system = platform.system()
        
        if "aarch64" in machine or "arm" in machine:
            if os.path.exists("/proc/device-tree/model"):
                with open("/proc/device-tree/model", "r") as f:
                    device = f.read().strip().replace("\x00", "")
            else:
                device = "ARM Device"
        elif system == "Darwin":
            device = "Apple Mac"
        elif system == "Linux":
            device = "Linux PC"
        else:
            device = f"{system} PC"
        
        cpu_count = os.cpu_count() or 1
        cpu_model = platform.processor() or "Unknown"
        cpu_info = f"{cpu_count}x {cpu_model}"
        
        ram_gb = 0.0
        if PSUTIL_AVAILABLE:
            ram_gb = psutil.virtual_memory().total / (1024**3)
        
        os_info = f"{system} {platform.release()}"
        
        return {
            "device": device,
            "cpu": cpu_info,
            "ram_gb": round(ram_gb, 1),
            "ram_human": f"{ram_gb:.1f} GB RAM",
            "os": os_info
        }
    except Exception as e:
        return {"error": str(e)}

def run_llama_cli(
    model_path: str,
    prompt: str,
    n_predict: int = 128,
    ctx_size: int = 2048,
    threads: int = 4,
    batch_size: int = 512,
    gpu_layers: int = 0,
    use_mlock: bool = False,
    ppl_mode: bool = False
) -> dict:
    """Run llama-cli in a PTY."""
    cmd = [
        "../llama.cpp/build/bin/llama-cli",
        "-m", model_path,
        "-n", str(n_predict),
        "-c", str(ctx_size),
        "--threads", str(threads),
        "--batch-size", str(batch_size),
        "--gpu-layers", str(gpu_layers),
        "-st",
    ]
    
    if use_mlock:
        cmd.append("--mlock")
    
    if not ppl_mode:
        cmd.extend(["-p", prompt])
    else:
        cmd.extend(["--ppl", "UNUSED", "-n", "0"])  # Will be overridden

    start_time = time.time()
    full_output = ""
    peak_memory_mb = None

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)
    else:
        try:
            if PSUTIL_AVAILABLE:
                proc = psutil.Process(pid)
                peak_memory_mb = 0.0
            else:
                proc = None

            while True:
                if proc is not None:
                    try:
                        if proc.is_running():
                            mem_mb = proc.memory_info().rss / (1024 * 1024)
                            peak_memory_mb = max(peak_memory_mb, mem_mb)
                        else:
                            break
                    except psutil.NoSuchProcess:
                        break

                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(fd, 1024)
                        if not data:
                            break
                        full_output += data.decode('utf-8', errors='ignore')
                    except OSError:
                        break
                else:
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except OSError:
                        break

        finally:
            os.close(fd)
            try:
                os.waitpid(pid, 0)
            except OSError:
                pass

    exec_time = time.time() - start_time

    tokens_per_sec = None
    for line in full_output.splitlines():
        if "Generation:" in line and "t/s" in line:
            try:
                after_gen = line.split("Generation:", 1)[1]
                speed_val = after_gen.strip().split()[0]
                tokens_per_sec = float(speed_val)
                break
            except (ValueError, IndexError):
                continue

    output_text = ""
    if not ppl_mode:
        lines = full_output.splitlines()
        capturing = False
        for line in lines:
            if "[Start thinking]" in line:
                capturing = True
                continue
            if not capturing:
                continue
            if (line.strip().startswith(">") or
                "[ Prompt:" in line or
                "Exiting..." in line or
                "available commands" in line or
                "build      :" in line or
                "model      :" in line or
                "modalities" in line or
                "▄▄" in line or "██" in line or
                "llama_memory_breakdown_print" in line or
                line.startswith("warning:")):
                continue
            output_text += line + "\n"
        output_text = output_text.strip()

    return {
        "tokens_per_sec": tokens_per_sec,
        "peak_memory_mb": peak_memory_mb,
        "exec_time_sec": exec_time
    }

def calculate_perplexity(model_path, ctx_size, threads, batch_size, gpu_layers):
    """Calculate perplexity using llama-perplexity with timeout."""
    try:
        # Use wiki.test.raw file from the same directory as this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        wiki_file = os.path.join(script_dir, "wiki.test.raw")
        
        if not os.path.exists(wiki_file):
            print(f"  PPL: ERROR: wiki.test.raw not found at {wiki_file}", flush=True)
            return None
                
        cmd = [
            "../llama.cpp/build/bin/llama-perplexity",
            "-m", model_path,
            "-f", wiki_file,
            "-c", str(ctx_size),
            "-t", str(threads),
            "--batch-size", str(batch_size),
            "--gpu-layers", str(gpu_layers),
        ]
        
        # Use subprocess.run with timeout - much more reliable than manual polling
        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=6000,  # 100 minute timeout
                check=False  # Don't raise on non-zero exit
            )
        except subprocess.TimeoutExpired:
            print("  PPL: TIMEOUT (100 minutes exceeded)", flush=True)
            return None
        
        elapsed = time.time() - start_time
        stdout = result.stdout
        stderr = result.stderr
        
        # Parse perplexity from output (check both stdout and stderr)
        ppl_score = None
        
        # Try stdout first
        for line in stdout.splitlines():
            # Look for patterns like "perplexity = 2.345" or "perplexity: 2.345"
            if "perplexity" in line.lower():
                # Try various formats
                patterns = [
                    r"perplexity\s*[=:]\s*([\d.]+)",
                    r"ppl\s*[=:]\s*([\d.]+)",
                ]
                for pattern in patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        try:
                            ppl_score = float(match.group(1))
                            print(f"  PPL: Found in stdout: {ppl_score:.4f}", flush=True)
                            break
                        except ValueError:
                            continue
                if ppl_score is not None:
                    break
        
        # If not found in stdout, check stderr
        if ppl_score is None:
            for line in stderr.splitlines():
                if "perplexity" in line.lower():
                    patterns = [
                        r"perplexity\s*[=:]\s*([\d.]+)",
                        r"ppl\s*[=:]\s*([\d.]+)",
                    ]
                    for pattern in patterns:
                        match = re.search(pattern, line, re.IGNORECASE)
                        if match:
                            try:
                                ppl_score = float(match.group(1))
                                break
                            except ValueError:
                                continue
                    if ppl_score is not None:
                        break
                
        return ppl_score
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None

def detect_outliers(values: list) -> list:
    """
    Detect outliers using a relaxed IQR method suitable for real-world benchmarking.
    Only flags values that are clearly broken (e.g., Q2_K reporting 100+ t/s).
    """
    if len(values) < 3:
        return []
    
    # Sort values and calculate basic stats
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    
    # Use median instead of mean (more robust to outliers)
    median_idx = n // 2
    median = sorted_vals[median_idx]
    
    # Calculate IQR but use much more relaxed thresholds
    q1_idx = n // 4
    q3_idx = (3 * n) // 4
    q1 = sorted_vals[q1_idx]
    q3 = sorted_vals[q3_idx]
    iqr = q3 - q1
    
    # Only flag extreme outliers (5x IQR instead of 1.5x)
    if iqr > 0:
        lower_bound = q1 - 5.0 * iqr
        upper_bound = q3 + 5.0 * iqr
    else:
        # If all values are similar, use median-based bounds
        lower_bound = median * 0.5  # 50% below median
        upper_bound = median * 3.0  # 300% above median
    
    # Additional safety: never flag values within reasonable range
    # For small models on good hardware, 5-50 t/s is normal
    # Only flag if truly extreme (e.g., Q2_K reporting 200+ t/s)
    absolute_lower = min(5.0, median * 0.3)  # Never flag below 5 t/s unless median is very low
    absolute_upper = max(80.0, median * 4.0)  # Only flag above 80 t/s or 4x median
    
    final_lower = max(lower_bound, absolute_lower)
    final_upper = min(upper_bound, absolute_upper)
    
    outlier_indices = []
    for i, val in enumerate(values):
        if val < final_lower or val > final_upper:
            outlier_indices.append(i)
    
    return outlier_indices

def benchmark_model(
    model_path: str,
    prompts: list,
    n_predict: int = 128,
    ctx_size: int = 2048,
    threads: int = 4,
    batch_size: int = 512,
    gpu_layers: int = 0,
    use_mlock: bool = False,
    include_ppl: bool = True,
    huggingface_repo: str = None,
) -> dict:
    print(f"Benchmarking {os.path.basename(model_path)}...")
    
    results = []
    tps_values = []  # Collect all tokens_per_sec values for outlier detection

    for i, prompt in enumerate(prompts):
        print(f"  Running prompt {i+1}/{len(prompts)}...", end="", flush=True)
        try:
            res = run_llama_cli(
                model_path=model_path,
                prompt=prompt,
                n_predict=n_predict,
                ctx_size=ctx_size,
                threads=threads,
                batch_size=batch_size,
                gpu_layers=gpu_layers,
                use_mlock=use_mlock,
                ppl_mode=False
            )
            if res["tokens_per_sec"] is not None:
                results.append(res)
                tps_values.append(res["tokens_per_sec"])
                print(f" {res['tokens_per_sec']:.2f} t/s")
            else:
                print(" FAILED (no speed)")
        except Exception as e:
            print(f" ERROR: {e}")

    # Detect and filter outliers
    outlier_count = 0
    valid_tps_values = []
    if len(tps_values) >= 3:
        outlier_indices = set(detect_outliers(tps_values))
        if outlier_indices:
            # Mark outliers in results and report them
            for idx, tps_val in enumerate(tps_values):
                if idx in outlier_indices:
                    print(f"  ⚠️  Detected outlier: prompt {idx+1} with {tps_val:.2f} t/s (ignoring for average)")
                    results[idx]["is_outlier"] = True
                    outlier_count += 1
                else:
                    valid_tps_values.append(tps_val)
        else:
            valid_tps_values = tps_values.copy()
    else:
        valid_tps_values = tps_values.copy()
    
    # Calculate average from non-outlier values
    avg_tps = sum(valid_tps_values) / len(valid_tps_values) if valid_tps_values else 0.0

    memory_vals = [r["peak_memory_mb"] for r in results if r["peak_memory_mb"] is not None]
    peak_memory_mb = max(memory_vals) if memory_vals else None

    # Calculate perplexity using --ppl with temp file (if enabled)
    ppl_score = None
    if include_ppl:
        print("  Calculating perplexity...", end="", flush=True)
        ppl_score = calculate_perplexity(model_path, ctx_size, threads, batch_size, gpu_layers)
        print(f" {ppl_score:.2f}" if ppl_score else " N/A")
    else:
        print("  Skipping perplexity calculation (--no-ppl)", flush=True)

    # Normalize model name: remove extension and decode percent-encodings
    # (e.g. convert "%3A" or double-encoded "%253A" into ":") so
    # we get a consistent format like `Qwen3-0.6B-f16-imatrix:Q4_K_M`.
    try:
        from urllib.parse import unquote
        base = os.path.splitext(os.path.basename(model_path))[0]
        # If it looks like a percent-encoded colon, decode once or twice
        if '%3a' in base.lower() or '%253a' in base.lower():
            decoded = unquote(base)
            # handle double-encoded values ("%253A" -> "%3A" -> ":")
            if '%3a' in decoded.lower() or '%253a' in decoded.lower():
                decoded = unquote(decoded)
            model_name = decoded
        else:
            model_name = base
    except Exception:
        # Fallback to basename if anything goes wrong
        model_name = os.path.splitext(os.path.basename(model_path))[0]
    parameters = extract_parameters_from_name(model_path)
    if parameters is None:
        parameters = extract_parameters_from_name(model_name)

    # Extract HuggingFace repo URL if not provided
    if huggingface_repo is None:
        huggingface_repo = extract_huggingface_repo_from_gguf(model_path)

    # Create human-readable benchmark command string
    cmd_parts = [
        f"--n-predict {n_predict}",
        f"--ctx-size {ctx_size}",
        f"--threads {threads}",
        f"--batch-size {batch_size}",
        f"--gpu-layers {gpu_layers}"
    ]
    if use_mlock:
        cmd_parts.append("--mlock")
    if not include_ppl:
        cmd_parts.append("--no-ppl")
    benchmark_command = " ".join(cmd_parts)

    return {
        "model_name": model_name,
        "parameters": parameters,
        "file_size_mb": get_model_size_mb(model_path),
        "avg_tokens_per_sec": avg_tps,
        "outliers_detected": outlier_count,
        "perplexity": ppl_score,  # Now correctly populated
        "peak_memory_mb": peak_memory_mb,
        "huggingface_repo": huggingface_repo,
        "total_exec_time_sec": sum(r["exec_time_sec"] for r in results if r["exec_time_sec"] is not None),
        "per_prompt_results": results,
        "date_checked": datetime.now().isoformat(),
        "benchmark_config": {
            "n_predict": n_predict,
            "ctx_size": ctx_size,
            "threads": threads,
            "batch_size": batch_size,
            "gpu_layers": gpu_layers,
            "mlock": use_mlock,
            "include_ppl": include_ppl,
            "num_prompts": len(prompts)
        },
        "benchmark_command": benchmark_command,
        "hardware_config": {
            "threads": threads,
            "ctx_size": ctx_size,
            "gpu_layers": gpu_layers,
            "batch_size": batch_size,
            "mlock": use_mlock
        },
        "system_info": detect_hardware_info(),
    }

def get_unique_key(entry: dict) -> str:
    """Generate a unique key for duplicate detection based on model name and system info."""
    model_name = entry.get("model_name", "unknown")
    system_info = entry.get("system_info", {})
    
    # Create a hardware fingerprint from key system info fields
    device = system_info.get("device", "unknown")
    cpu = system_info.get("cpu", "unknown")
    os_info = system_info.get("os", "unknown")
    
    # Combine model name with hardware info to create unique identifier
    return f"{model_name}|{device}|{cpu}|{os_info}"

def save_leaderboard(leaderboard_path: str, new_result: dict):
    try:
        os.makedirs(os.path.dirname(leaderboard_path), exist_ok=True)
    except (PermissionError, FileNotFoundError) as e:
        print(f"ERROR: Cannot create directory for '{leaderboard_path}': {e}", file=sys.stderr)
        sys.exit(1)
    
    leaderboard = []
    if os.path.exists(leaderboard_path):
        try:
            with open(leaderboard_path, 'r') as f:
                leaderboard = json.load(f)
        except json.JSONDecode:
            print(f"WARNING: Corrupted leaderboard.json. Starting fresh.", file=sys.stderr)
    
    # Use unique key (model + hardware) for duplicate detection
    new_key = get_unique_key(new_result)
    leaderboard = [entry for entry in leaderboard if get_unique_key(entry) != new_key]
    leaderboard.append(new_result)
    leaderboard.sort(key=lambda x: x.get("avg_tokens_per_sec", 0), reverse=True)
    
    temp_path = leaderboard_path + ".tmp"
    with open(temp_path, 'w') as f:
        json.dump(leaderboard, f, indent=2)
    os.replace(temp_path, leaderboard_path)
    
    print(f"\nLeaderboard saved to {os.path.abspath(leaderboard_path)}")

def upload_to_github():
    """Commit and push ONLY docs/leaderboard.json to GitHub."""
    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], 
                      check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        try:
            subprocess.run(["git", "config", "user.name"], 
                          check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            subprocess.run(["git", "config", "user.name", "QuantBoard Bot"])
            subprocess.run(["git", "config", "user.email", "quantboard@users.noreply.github.com"])
        
        if not os.path.exists("docs/leaderboard.json"):
            print("⚠️ docs/leaderboard.json not found. Skipping upload.")
            return

        # Determine current branch
        try:
            branch_proc = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            current_branch = branch_proc.stdout.strip()
        except subprocess.CalledProcessError:
            current_branch = None

        # Pull remote changes first to merge any updates that occurred while benchmarking
        if current_branch:
            try:
                pull_proc = subprocess.run([
                    "git", "pull", "origin", current_branch
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                # success - continue
            except subprocess.CalledProcessError as e:
                stderr = e.stderr or ""
                # If there are merge conflicts, abort upload and notify the user
                if "CONFLICT" in stderr or "Automatic merge failed" in stderr or "Merge conflict" in stderr:
                    print("⚠️ Git merge conflicts detected after pulling remote changes.")
                    print("   Please resolve conflicts for 'docs/leaderboard.json' and re-run the benchmark.", file=sys.stderr)
                    return
                else:
                    print(f"⚠️ Git pull failed: {stderr.strip()}", file=sys.stderr)
                    return

        # Only commit+push if the file actually changed compared to HEAD
        result = subprocess.run(
            ["git", "diff", "--quiet", "docs/leaderboard.json"],
            capture_output=True
        )
        if result.returncode == 0:
            print("ℹ️ No changes to docs/leaderboard.json. Skipping upload.")
            return

        subprocess.run(["git", "add", "docs/leaderboard.json"], check=True)
        commit_msg = f"Update leaderboard: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "push"], check=True)
        print("✅ Leaderboard uploaded to GitHub!")
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode().strip() if e.stderr else str(e)
        if "Authentication failed" in error_msg or "Permission denied" in error_msg:
            print("⚠️ GitHub authentication failed!", file=sys.stderr)
            print("   Configure SSH keys or a Personal Access Token.", file=sys.stderr)
        else:
            print(f"⚠️ Git error: {error_msg}", file=sys.stderr)
    except FileNotFoundError:
        print("⚠️ Git not installed. Skipping GitHub upload.", file=sys.stderr)

def print_summary(result: dict):
    print("\n" + "="*60)
    print(f"MODEL: {result['model_name']} ({result['parameters']})")
    if result.get('huggingface_repo'):
        print(f"HuggingFace: {result['huggingface_repo']}")
    print(f"Size: {result['file_size_mb']:.1f} MB")
    print(f"Speed: {result['avg_tokens_per_sec']:.2f} tokens/sec")
    print(f"Perplexity: {result['perplexity']:.2f}" if result['perplexity'] else "Perplexity: N/A")
    if result['peak_memory_mb']:
        print(f"Peak RAM: {result['peak_memory_mb']:.1f} MB")
    cfg = result['hardware_config']
    print(f"Config: threads={cfg['threads']}, ctx={cfg['ctx_size']}, gpu={cfg['gpu_layers']}")
    sys_info = result['system_info']
    print(f"Hardware: {sys_info.get('device', 'N/A')}")
    print(f"          System RAM: {sys_info.get('ram_human', 'N/A')} • CPU: {sys_info.get('cpu', 'N/A')}")
    print(f"Date Checked: {result['date_checked']}")
    print("="*60)

def main():
    parser = argparse.ArgumentParser(description="Non-interactive quantized model benchmark for llama.cpp")
    parser.add_argument("model_path", help="Path to GGUF model file")
    parser.add_argument("--leaderboard", default="docs/leaderboard.json", help="Output JSON file")
    parser.add_argument("--prompts", nargs="*", help="Custom prompts")
    parser.add_argument("--n-predict", type=int, default=128, help="Tokens to generate")
    parser.add_argument("--ctx-size", type=int, default=2048, help="Context size")
    parser.add_argument("--threads", type=int, default=min(4, os.cpu_count() or 4), help="Threads")
    parser.add_argument("--batch-size", type=int, default=512, help="Batch size")
    parser.add_argument("--gpu-layers", type=int, default=0, help="GPU offload layers")
    parser.add_argument("--mlock", action="store_true", help="Lock model in RAM")
    parser.add_argument("--no-ppl", action="store_true", help="Skip perplexity calculation (useful for low-spec machines)")
    parser.add_argument("--no-upload", action="store_true", help="Skip GitHub upload")
    parser.add_argument("--no-save", action="store_true", help="Skip saving to leaderboard")
    parser.add_argument("--huggingface-repo", type=str, default=None, help="HuggingFace repository URL (e.g., https://huggingface.co/user/repo or user/repo). If not provided, will attempt to extract from GGUF metadata.")

    args = parser.parse_args()

    if not os.path.exists("../llama.cpp/build/bin/llama-cli"):
        print("ERROR: ../llama.cpp/build/bin/llama-cli not found. Please build llama.cpp first.")
        sys.exit(1)

    if not os.path.isfile(args.model_path):
        print(f"ERROR: Model file not found: {args.model_path}")
        sys.exit(1)

    prompts = args.prompts if args.prompts else PROMPTS

    # Normalize HuggingFace repo URL if provided
    hf_repo = args.huggingface_repo
    if hf_repo and not hf_repo.startswith("http"):
        # If it's just "user/repo", convert to full URL
        hf_repo = f"https://huggingface.co/{hf_repo}"

    result = benchmark_model(
        model_path=args.model_path,
        prompts=prompts,
        n_predict=args.n_predict,
        ctx_size=args.ctx_size,
        threads=args.threads,
        batch_size=args.batch_size,
        gpu_layers=args.gpu_layers,
        use_mlock=args.mlock,
        include_ppl=not args.no_ppl,
        huggingface_repo=hf_repo
    )

    print_summary(result)

    if not args.no_save:
        save_leaderboard(args.leaderboard, result)
        if not args.no_upload:
            upload_to_github()

    print("\n✅ Benchmark completed successfully!")

if __name__ == "__main__":
    main()