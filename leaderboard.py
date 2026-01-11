#!/usr/bin/env python3
"""
Quantized Model Leaderboard for llama.cpp — Non-Interactive Benchmark

Features:
- Tokens/sec from TTY output
- Peak RAM usage (runtime)
- System RAM (GB) as separate column
- Perplexity (always measured)
- Accurate parameter count via GGUF metadata (new API)
- Hardware detection (Raspberry Pi, CPU, OS)
- Saves to ./docs/leaderboard.json
- Includes "Date Checked" timestamp
- Optional GitHub auto-upload
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

PPL_PROMPT = (
    "The quick brown fox jumps over the lazy dog. "
    "Natural language processing enables computers to understand human language. "
    "Machine learning models require large datasets for training. "
    "Quantization reduces model size while preserving performance."
)

def get_model_size_mb(model_path: str) -> float:
    return os.path.getsize(model_path) / (1024 * 1024)

def extract_parameters_from_gguf(model_path: str) -> str:
    """Extract parameter count from GGUF metadata (new API)."""
    if not GGUF_AVAILABLE:
        return None
    try:
        reader = GGUFReader(model_path)
        # New API: use .fields dictionary
        if "general.parameter_count" in reader.fields:
            count = reader.fields["general.parameter_count"].parts[-1]
            if isinstance(count, int):
                if count >= 10**9:
                    return f"{count / 1e9:.1f}B"
                elif count >= 10**6:
                    return f"{count / 1e6:.1f}M"
                else:
                    return f"{count}"
        return None
    except Exception as e:
        print(f"GGUF metadata read error: {e}", file=sys.stderr)
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
        
        # Get numeric RAM value (GB)
        ram_gb = 0.0
        if PSUTIL_AVAILABLE:
            ram_gb = psutil.virtual_memory().total / (1024**3)
        
        os_info = f"{system} {platform.release()}"
        
        return {
            "device": device,
            "cpu": cpu_info,
            "ram_gb": round(ram_gb, 1),      # ← Numeric value for sorting
            "ram_human": f"{ram_gb:.1f} GB RAM",  # ← Human-readable
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
        "./build/bin/llama-cli",
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
        cmd.extend(["--ppl-str", PPL_PROMPT, "-n", "0"])

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
        "exec_time_sec": exec_time,
        "output_text": output_text,
        "captured_output": full_output
    }

def benchmark_model(
    model_path: str,
    prompts: list,
    n_predict: int = 128,
    ctx_size: int = 2048,
    threads: int = 4,
    batch_size: int = 512,
    gpu_layers: int = 0,
    use_mlock: bool = False,
    include_ppl: bool = True  # Always include PPL now
) -> dict:
    print(f"Benchmarking {os.path.basename(model_path)}...")
    
    results = []
    total_tps = 0.0
    valid_runs = 0

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
                total_tps += res["tokens_per_sec"]
                valid_runs += 1
                print(f" {res['tokens_per_sec']:.2f} t/s")
            else:
                print(" FAILED (no speed)")
        except Exception as e:
            print(f" ERROR: {e}")

    avg_tps = total_tps / valid_runs if valid_runs > 0 else 0.0

    memory_vals = [r["peak_memory_mb"] for r in results if r["peak_memory_mb"] is not None]
    peak_memory_mb = max(memory_vals) if memory_vals else None

    # ALWAYS calculate perplexity (critical for quant evaluation)
    ppl_score = None
    print("  Calculating perplexity...", end="", flush=True)
    try:
        cmd = [
            "./build/bin/llama-cli",
            "-m", model_path,
            "--ppl-str", PPL_PROMPT,
            "-n", "0",
            "-c", str(ctx_size),
            "--threads", str(threads),
            "--batch-size", str(batch_size),
            "--gpu-layers", str(gpu_layers),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in result.stderr.splitlines():
            if "perplexity" in line.lower():
                try:
                    ppl_score = float(line.split()[-1])
                    break
                except (ValueError, IndexError):
                    pass
        print(f" {ppl_score:.2f}" if ppl_score else " N/A")
    except Exception as e:
        print(f" PPL ERROR: {e}")

    model_name = os.path.basename(model_path)
    
    # Get parameters: GGUF first, then filename
    parameters = extract_parameters_from_gguf(model_path)
    if parameters is None:
        parameters = extract_parameters_from_name(model_name)

    return {
        "model_path": os.path.abspath(model_path),
        "model_name": model_name,
        "parameters": parameters,
        "file_size_mb": get_model_size_mb(model_path),
        "avg_tokens_per_sec": avg_tps,
        "perplexity": ppl_score,  # ← FIXED TYPO
        "peak_memory_mb": peak_memory_mb,
        "total_exec_time_sec": sum(r["exec_time_sec"] for r in results if r["exec_time_sec"] is not None),
        "per_prompt_results": results,
        "date_checked": datetime.now().isoformat(),
        "hardware_config": {
            "threads": threads,
            "ctx_size": ctx_size,
            "gpu_layers": gpu_layers,
            "batch_size": batch_size,
            "mlock": use_mlock
        },
        "system_info": detect_hardware_info(),
    }

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
        except json.JSONDecodeError:
            print(f"WARNING: Corrupted leaderboard.json. Starting fresh.", file=sys.stderr)
    
    # Remove existing entry with same model_path (prevent duplicates)
    leaderboard = [entry for entry in leaderboard if entry["model_path"] != new_result["model_path"]]
    leaderboard.append(new_result)
    leaderboard.sort(key=lambda x: x.get("avg_tokens_per_sec", 0), reverse=True)
    
    # Atomic write
    temp_path = leaderboard_path + ".tmp"
    with open(temp_path, 'w') as f:
        json.dump(leaderboard, f, indent=2)
    os.replace(temp_path, leaderboard_path)
    
    print(f"\nLeaderboard saved to {os.path.abspath(leaderboard_path)}")

def upload_to_github():
    """Commit and push ONLY docs/leaderboard.json to GitHub."""
    try:
        # Verify we're in a git repo
        subprocess.run(["git", "rev-parse", "--git-dir"], 
                      check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Configure git user if missing
        try:
            subprocess.run(["git", "config", "user.name"], 
                          check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            subprocess.run(["git", "config", "user.name", "QuantBoard Bot"])
            subprocess.run(["git", "config", "user.email", "quantboard@users.noreply.github.com"])
        
        # Check if leaderboard.json exists
        if not os.path.exists("docs/leaderboard.json"):
            print("⚠️ docs/leaderboard.json not found. Skipping upload.")
            return
        
        # Check if file has changed
        result = subprocess.run(
            ["git", "diff", "--quiet", "docs/leaderboard.json"],
            capture_output=True
        )
        if result.returncode == 0:
            print("ℹ️ No changes to docs/leaderboard.json. Skipping upload.")
            return
        
        # Stage ONLY the leaderboard file
        subprocess.run(["git", "add", "docs/leaderboard.json"], check=True)
        
        # Commit with specific message
        commit_msg = f"Update leaderboard: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        
        # Push ONLY the current branch
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
    parser.add_argument("--no-upload", action="store_true", help="Skip GitHub upload")
    parser.add_argument("--no-save", action="store_true", help="Skip saving to leaderboard")

    args = parser.parse_args()

    if not os.path.exists("./build/bin/llama-cli"):
        print("ERROR: ./build/bin/llama-cli not found. Please build llama.cpp first.")
        sys.exit(1)

    if not os.path.isfile(args.model_path):
        print(f"ERROR: Model file not found: {args.model_path}")
        sys.exit(1)

    prompts = args.prompts if args.prompts else PROMPTS

    result = benchmark_model(
        model_path=args.model_path,
        prompts=prompts,
        n_predict=args.n_predict,
        ctx_size=args.ctx_size,
        threads=args.threads,
        batch_size=args.batch_size,
        gpu_layers=args.gpu_layers,
        use_mlock=args.mlock
    )

    print_summary(result)

    if not args.no_save:
        save_leaderboard(args.leaderboard, result)
        if not args.no_upload:
            upload_to_github()

    print("\n✅ Benchmark completed successfully!")

if __name__ == "__main__":
    main()