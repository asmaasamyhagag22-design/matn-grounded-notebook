"""Start Matn with ./app.sh. All document work stays on this computer."""
import argparse
import json
import signal
import threading

from .runtime import DATA_ROOT, preflight
from .server import make_server
from .service import App


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data", default=str(DATA_ROOT / "app"))
    parser.add_argument("--search-budget", type=int, default=0, help="Explicit total search allowance for this app data folder; a run reserves 12")
    parser.add_argument("--fake", action="store_true", help="Clearly labelled fixture mode; no real model/search")
    parser.add_argument("--check", action="store_true", help="Read-only local preflight, no provider or search calls")
    parser.add_argument("--dev-research-v2", action="store_true", help="Developer only: allow the experimental research v2 path (off by default)")
    parser.add_argument("--answer-profile", help="JSON profile with answer_path set to v2 or v3")
    args = parser.parse_args()
    from .answer_profile import load_answer_profile
    profile = load_answer_profile(args.answer_profile)
    if args.check:
        readiness = preflight(fake=args.fake, search_budget=args.search_budget)
        print(json.dumps(readiness, indent=2))
        return 0 if readiness["verdict"] == "GO" else 2
    app = App(args.data, fake=args.fake, search_budget=args.search_budget, research_v2=args.dev_research_v2, answer_profile=profile)
    server = make_server(app, args.port)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("Matn · http://127.0.0.1:" + str(server.server_port) + " · local preflight " + app.readiness["verdict"], flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        app.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
