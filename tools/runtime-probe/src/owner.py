"""Local POSIX owner lease, held until the Node parent's stdin pipe closes.

Never unlink the lease inode: competing openers must lock the same file.
"""
import fcntl
import sys

with open(sys.argv[1], "a", encoding="utf-8") as lease:
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("storage already owned", file=sys.stderr, flush=True)
        sys.exit(2)
    print("owned", flush=True)
    sys.stdin.buffer.read()
