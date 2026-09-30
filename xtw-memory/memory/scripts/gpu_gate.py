"""RTX 5060 Ti 16GB Shared Exclusive GPU Gate and Lock Manager.

Operational Invariant:
- RTX 5060 Ti 16GB is a shared exclusive resource.
- Any CUDA benchmark, model inference service, or training task MUST acquire the GPU lock before launching.
- NEVER run concurrently with any other GPU workload.
- CPU stages may run in parallel.
- If the lock cannot be acquired, DO NOT kill existing tasks; halt at the GPU gate until resources are released.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional


LOCK_FILE_PATH = Path("/tmp/opencode/gpu_rtx5060ti.lock")


def get_active_gpu_processes() -> List[int]:
    """Queries nvidia-smi for active compute process PIDs on the GPU."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            pids = []
            for line in res.stdout.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
            return pids
    except Exception:
        pass
    return []


class GpuLock:
    """Context manager for exclusive access to RTX 5060 Ti 16GB."""

    def __init__(
        self,
        lock_path: Path = LOCK_FILE_PATH,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
        job_name: str = "GPU_WORKLOAD",
    ):
        self.lock_path = lock_path
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.job_name = job_name
        self.file_descriptor: Optional[int] = None
        self._acquired = False

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        my_pid = os.getpid()

        self.file_descriptor = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o666)

        first_wait_logged = False

        while True:
            # 1. Check if another process holds the flock
            try:
                fcntl.flock(self.file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                flock_ok = True
            except (BlockingIOError, IOError):
                flock_ok = False

            # 2. Check if nvidia-smi reports compute applications from another PID
            active_pids = [p for p in get_active_gpu_processes() if p != my_pid]

            if flock_ok and len(active_pids) == 0:
                # Acquired exclusive lock
                os.ftruncate(self.file_descriptor, 0)
                os.write(
                    self.file_descriptor,
                    f"PID={my_pid}\nJOB={self.job_name}\nTIMESTAMP={time.time()}\n".encode("utf-8"),
                )
                self._acquired = True
                print(f"[GPU GATE] Successfully acquired exclusive lock for RTX 5060 Ti 16GB (PID: {my_pid}, Job: {self.job_name})")
                return True

            # If flock was acquired but external GPU compute app is running, release flock while waiting
            if flock_ok:
                try:
                    fcntl.flock(self.file_descriptor, fcntl.LOCK_UN)
                except Exception:
                    pass

            if not first_wait_logged:
                print(f"[GPU GATE] RTX 5060 Ti 16GB is occupied. Active GPU PIDs: {active_pids or 'locked by file'}. Halting at GPU gate...")
                first_wait_logged = True

            if self.timeout is not None and (time.time() - start_time) > self.timeout:
                raise TimeoutError(f"[GPU GATE] Timeout ({self.timeout}s) waiting for RTX 5060 Ti 16GB to be released.")

            time.sleep(self.poll_interval)

    def release(self) -> None:
        if self._acquired and self.file_descriptor is not None:
            try:
                os.ftruncate(self.file_descriptor, 0)
                fcntl.flock(self.file_descriptor, fcntl.LOCK_UN)
                os.close(self.file_descriptor)
                self.file_descriptor = None
                self._acquired = False
                print(f"[GPU GATE] Released exclusive lock for RTX 5060 Ti 16GB.")
            except Exception as e:
                print(f"[GPU GATE] Warning during lock release: {e}", file=sys.stderr)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 gpu_gate.py [status|wait|run -- <command>]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        pids = get_active_gpu_processes()
        print(f"Active GPU compute PIDs: {pids}")
        if LOCK_FILE_PATH.exists():
            content = LOCK_FILE_PATH.read_text().strip()
            print(f"Lock file info:\n{content}")
        else:
            print("Lock file does not exist.")
    elif cmd == "wait":
        print("[GPU GATE] Waiting until RTX 5060 Ti 16GB is fully idle and available...")
        with GpuLock(job_name="cli-wait"):
            print("[GPU GATE] GPU is now free!")
    elif cmd == "run":
        if "--" not in sys.argv:
            print("Usage: python3 gpu_gate.py run -- <command>")
            sys.exit(1)
        subcmd_idx = sys.argv.index("--") + 1
        subcmd = sys.argv[subcmd_idx:]
        job_label = " ".join(subcmd[:2])
        with GpuLock(job_name=job_label):
            res = subprocess.run(subcmd)
            sys.exit(res.returncode)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
