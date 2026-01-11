#!/usr/bin/env python3
"""
Quantized Model Leaderboard for llama.cpp — Non-Interactive Benchmark

Captures:
- Tokens/sec (from TTY output)
- Peak RAM usage
- Model parameter count (e.g., 0.6B)
- Hardware info (Raspberry Pi, RAM, CPU, OS)

Tested with custom quants (Q3_K_HIFI) and llama.cpp build b7548.
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

# Try to import psutil for memory monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: 'psutil' not installed. Peak memory will not be recorded.", file=sys.stderr)
    print("Install with: pip install psutil", file=sys.stderr)

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

def extract_parameters_from_name(model_name: str) -> str:
    """Extract parameter count from model name (e.g., 'Qwen3-0.6B' -> '0.6B')."""
    # Remove extension
    base_name = os.path.splitext(model_name)[0]
    # Common patterns: Qwen3-0.6B, Mistral-7B, Phi-3-3.8B, etc.
    match = re.search(r'(\d+\.?\d*[BbMm])', base_name)
    if match:
        return match.group(1).upper().replace('M', 'M').replace('B', 'B')
    # Fallback heuristics
    if any(x in base_name for x in ['0.5', '0.6', 'tiny']):
        return "0.6B"
    elif '1.5' in base_name:
        return "1.5B"
    elif '3' in base_name and '7' not in base_name and '13' not in base_name:
        return "3B"
    elif '7' in base_name:
        return "7B"
    elif '13' in base_name:
        return "13B"
    elif '34' in base_name:
        return "34B"
    return "Unknown"

def detect_hardware_info():
    """Detect hardware info (device, CPU, RAM, OS)."""
    try:
        # Device type
        device = "Unknown Device"
        machine = platform.machine().lower()
        system = platform.system()
        
        if "aarch64" in machine or "arm" in machine:
            # Raspberry Pi detection
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
        
        # CPU info
        cpu_count = os.cpu_count() or 1
        cpu_model = platform.processor() or "Unknown"
        cpu_info = f"{cpu_count}x {cpu_model}"
        
        # RAM
        if PSUTIL_AVAILABLE:
            ram_gb = psutil.virtual_memory().total / (1024**3)
            ram_info = f"{ram_gb:.1f} GB RAM"
        else:
            ram_info = "RAM unknown"
        
        # OS
        os_info = f"{system} {platform.release()}"
        
        return {
            "device": device,
            "cpu": cpu_info,
            "ram": ram_info,
            "os": os_info,
            "timestamp": time.time()
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
    """Run llama-cli in a PTY and monitor memory with psutil."""
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

    # Launch in PTY
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

    # Parse tokens/sec from TTY output
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

    # Extract generated text
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
    include_ppl: bool = False
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

    # Safely compute peak memory
    memory_vals = [r["peak_memory_mb"] for r in results if r["peak_memory_mb"] is not None]
    peak_memory_mb = max(memory_vals) if memory_vals else None

    # Perplexity
    ppl_score = None
    if include_ppl and valid_runs > 0:
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
    return {
        "model_path": os.path.abspath(model_path),
        "model_name": model_name,
        "parameters": extract_parameters_from_name(model_name),  # ← NEW
        "file_size_mb": get_model_size_mb(model_path),
        "avg_tokens_per_sec": avg_tps,
        "peak_memory_mb": peak_memory_mb,
        "total_exec_time_sec": sum(r["exec_time_sec"] for r in results if r["exec_time_sec"] is not None),
        "per_prompt_results": results,
        "perplexity": ppl_score,
        "timestamp": time.time(),
        "hardware_config": {
            "threads": threads,
            "ctx_size": ctx_size,
            "gpu_layers": gpu_layers,
            "batch_size": batch_size,
            "mlock": use_mlock
        },
        "system_info": detect_hardware_info(),  # ← NEW
    }

def save_leaderboard(leaderboard_path: str, new_result: dict):
    leaderboard = []
    if os.path.exists(leaderboard_path):
        with open(leaderboard_path, 'r') as f:
            leaderboard = json.load(f)
    
    leaderboard = [e for e in leaderboard if e["model_path"] != new_result["model_path"]]
    leaderboard.append(new_result)
    leaderboard.sort(key=lambda x: x.get("avg_tokens_per_sec", 0), reverse=True)
    
    with open(leaderboard_path, 'w') as f:
        json.dump(leaderboard, f, indent=2)
    print(f"\nLeaderboard saved to {leaderboard_path}")

def print_summary(result: dict):
    print("\n" + "="*60)
    print(f"MODEL: {result['model_name']} ({result['parameters']})")
    print(f"Size: {result['file_size_mb']:.1f} MB")
    print(f"Speed: {result['avg_tokens_per_sec']:.2f} tokens/sec")
    if result['peak_memory_mb']:
        print(f"Peak RAM: {result['peak_memory_mb']:.1f} MB")
    if result['perplexity']:
        print(f"Perplexity: {result['perplexity']:.2f}")
    cfg = result['hardware_config']
    print(f"Config: threads={cfg['threads']}, ctx={cfg['ctx_size']}, gpu={cfg['gpu_layers']}")
    sys_info = result['system_info']
    print(f"Hardware: {sys_info.get('device', 'N/A')}")
    print(f"          {sys_info.get('ram', 'N/A')} • {sys_info.get('cpu', 'N/A')}")
    print("="*60)

def main():
    parser = argparse.ArgumentParser(description="Non-interactive quantized model benchmark for llama.cpp")
    parser.add_argument("model_path", help="Path to GGUF model file")
    parser.add_argument("--leaderboard", default="leaderboard.json", help="Output JSON file")
    parser.add_argument("--prompts", nargs="*", help="Custom prompts")
    parser.add_argument("--n-predict", type=int, default=128, help="Tokens to generate")
    parser.add_argument("--ctx-size", type=int, default=2048, help="Context size")
    parser.add_argument("--threads", type=int, default=min(4, os.cpu_count() or 4), help="Threads")
    parser.add_argument("--batch-size", type=int, default=512, help="Batch size")
    parser.add_argument("--gpu-layers", type=int, default=0, help="GPU offload layers")
    parser.add_argument("--mlock", action="store_true", help="Lock model in RAM")
    parser.add_argument("--ppl", action="store_true", help="Include perplexity")
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
        use_mlock=args.mlock,
        include_ppl=args.ppl
    )

    print_summary(result)

    if not args.no_save:
        save_leaderboard(args.leaderboard, result)

    print("\n✅ Benchmark completed successfully!")

if __name__ == "__main__":
    main()