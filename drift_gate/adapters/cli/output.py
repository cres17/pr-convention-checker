"""UTF-8 output shared by CLI command handlers."""
import sys


def write_stdout(output: str) -> None:
    data = (output + "\n").encode("utf-8")
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(data)
    else:
        sys.stdout.write(output + "\n")


