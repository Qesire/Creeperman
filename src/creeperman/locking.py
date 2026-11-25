"""One local owner per acquisition ledger."""
from contextlib import contextmanager
import os

@contextmanager
def collector_lock(state):
    """One process for each local collector state. Cross-host ownership is operational."""
    from pathlib import Path
    p=Path(str(state)+".lock")
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a+b") as f:
        if os.name=="nt":
            import msvcrt
            f.seek(0,2)
            if f.tell()==0:f.write(b"0");f.flush()
            f.seek(0)
            try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError("collector state already in use")
            try:yield
            finally:
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError("collector state already in use")
            try:yield
            finally:fcntl.flock(f.fileno(),fcntl.LOCK_UN)

