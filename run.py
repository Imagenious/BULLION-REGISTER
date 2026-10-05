"""Run Bullion Register on this computer.

    python run.py            -> http://127.0.0.1:8000 (this computer only)
    python run.py --lan      -> also reachable from phones on the same Wi-Fi
"""
import argparse
import os
import socket

from waitress import serve

from app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bullion Register")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--lan", action="store_true", help="listen on the local network too")
    parser.add_argument("--db", help="use a different SQLite file (e.g. for a practice copy)")
    args = parser.parse_args()
    if args.db:
        os.environ["DATABASE_URL"] = "sqlite:///" + os.path.abspath(args.db)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    app = create_app()
    print(f"Bullion Register is running at http://127.0.0.1:{args.port}")
    if args.lan:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            print(f"On your Wi-Fi, open http://{ip}:{args.port} on your phone")
        except OSError:
            pass
    print("Press Ctrl+C to stop.")
    serve(app, host=host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
