import re
from pathlib import Path

LOG_DIR = Path(__file__).parent / "output" / "log"

log_files = [
    LOG_DIR / "cot_tokens.log",
    LOG_DIR / "generate_tokens.log",
    LOG_DIR / "rank_tokens.log",
]

total_tokens = 0

for log_file in log_files:
    try:
        with open(log_file, "r") as f:
            for line in f:
                # Try to find a number in the line (e.g., tokens=123 or just 123)
                match = re.search(r"['\"]total_tokens['\"]\s*[:=]\s*(\d+)", line)
                if match:
                    total_tokens += int(match.group(1))
                else:
                    # fallback: sum all standalone numbers in the line
                    for num in re.findall(r"\\b\\d+\\b", line):
                        total_tokens += int(num)
    except FileNotFoundError:
        print(f"File not found: {log_file}")

print(f"Total tokens: {total_tokens}")
