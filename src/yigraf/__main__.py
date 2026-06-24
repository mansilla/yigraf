"""``python -m yigraf`` entry point — used by the git hook, which bakes in an absolute interpreter
path so it works regardless of ``PATH`` (see :mod:`yigraf.hooks`)."""
from yigraf.cli import main

if __name__ == "__main__":
    main()
