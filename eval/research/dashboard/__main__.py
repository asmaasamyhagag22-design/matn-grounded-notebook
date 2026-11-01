"""Regenerate saved scoreboard, optionally serve the local run console."""
import argparse
from pathlib import Path

from .data import DELIVERY_ROOT, V2_ROOT
from .server import Console, make_server


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=DELIVERY_ROOT,help='Original delivery repository; artifacts are read from its out/')
    p.add_argument('--v2-root',type=Path,default=V2_ROOT)
    p.add_argument('--ledger',type=Path,action='append',help='Explicit console ledger allowlist (repeatable)')
    p.add_argument('--serve',action='store_true'); p.add_argument('--port',type=int,default=8765)
    args=p.parse_args(argv)
    ledgers=args.ledger or [args.root/'out/leap-20261030/meeting-ledger-v2',args.root/'out/leap-20261030/meeting-ledger']
    console=Console(args.root,args.v2_root,ledgers); result=console.build()
    print(str(console.output/'index.html')); print(f'{len(result["runs"])} saved runs; zero search/model calls')
    if args.serve:
        server=make_server(console,args.port)
        print(f'http://127.0.0.1:{server.server_port}/dashboard/index.html',flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()


if __name__=='__main__':
    main()
