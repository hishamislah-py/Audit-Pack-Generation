"""Start the local backend: python -m uc042app [--port 8000]

Always bound to 127.0.0.1 with a single worker process (no authentication; one analyst on this machine)."""
import argparse

import uvicorn


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m uc042app", description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    uvicorn.run("uc042app.api.main:create_app", factory=True, host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
