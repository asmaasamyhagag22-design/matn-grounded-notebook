"""Run immutable research code under Matn's current search retention policy (ADR-0035).

The app's default research path runs the frozen `delivery-2026-10-30` tree, which
cannot change. That code saved full search-provider bodies. This launcher loads
`matn_research/retention.py` from the current code by file path, wraps every search
provider class in the frozen tree so each result passes through `retention.envelope`,
and then runs the requested module from the frozen tree unchanged. If it finds no
provider class to wrap it stops before any search (fail closed). The frozen `live`
command re-launches itself as a supervised `--worker` process, where the searches run;
`matn_storyboard.budget.supervise` is wrapped so that worker also starts through this
launcher (any other supervised command stops the run).

  python -B matn_app/frozen_research.py --tree TREE -m matn_research live ...

Run by file path on purpose: `matn_app` inside TREE is the frozen copy.
"""
import importlib
import importlib.util
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
MARK = '__matn_retention__'


def load_retention():
    spec = importlib.util.spec_from_file_location('_matn_retention_policy', ROOT / 'matn_research' / 'retention.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enforce(providers, retention):
    """Wrap `search` on every provider class (a class with `name` and `search`) in `providers`."""
    wrapped = []
    for attr, cls in sorted(vars(providers).items()):
        if not (isinstance(cls, type) and cls.__module__ == providers.__name__
                and isinstance(getattr(cls, 'name', None), str) and callable(getattr(cls, 'search', None))):
            continue
        if getattr(cls.search, MARK, False):
            wrapped.append(attr)
            continue
        original = cls.search

        def search(self, query, _original=original):
            policy = retention.policy_of(self)  # unknown names fail before the request
            return retention.envelope(_original(self, query), policy)
        setattr(search, MARK, True)
        cls.search = search
        wrapped.append(attr)
    if not wrapped:
        raise SystemExit('FROZEN_RETENTION_TARGET_MISSING: no search provider class in ' + providers.__name__)
    return wrapped


def worker_command(command, tree, module):
    """[python, -m, MODULE, ...] -> [python, -B, THIS, --tree, TREE, -m, MODULE, ...]; anything else fails closed."""
    command = [str(x) for x in command]
    if command[1:3] != ['-m', module]:
        raise SystemExit('FROZEN_RETENTION_UNEXPECTED_WORKER: ' + ' '.join(command[:4]))
    return [command[0], '-B', str(HERE), '--tree', str(tree), '-m', module, *command[3:]]


def relaunch_workers(tree, module):
    """Route supervised worker processes of the frozen tree through this launcher too."""
    try:
        budget = importlib.import_module('matn_storyboard.budget')
    except ModuleNotFoundError:
        return False  # no supervisor in this tree: every search runs in this process
    if Path(budget.__file__).resolve().parent.parent != tree:
        raise SystemExit('FROZEN_RETENTION_WRONG_TREE: ' + budget.__file__)
    original = budget.supervise
    if getattr(original, MARK, False):
        return True

    def supervise(folder, phase, command, **kwargs):
        return original(folder, phase, worker_command(command, tree, module), **kwargs)
    setattr(supervise, MARK, True)
    budget.supervise = supervise
    return True


def main(argv):
    if len(argv) < 5 or argv[0] != '--tree' or argv[2] != '-m':
        raise SystemExit('usage: frozen_research.py --tree TREE -m MODULE [args...]')
    tree = Path(argv[1]).resolve()
    module = argv[3]
    # Only the frozen tree may provide packages; drop this file's folder and the current code root.
    drop = {HERE.parent, ROOT}
    sys.path[:] = [str(tree)] + [p for p in sys.path if p and Path(p).resolve() not in drop | {tree}]
    retention = load_retention()
    providers = importlib.import_module(module.split('.')[0] + '.providers')
    if Path(providers.__file__).resolve().parent.parent != tree:
        raise SystemExit('FROZEN_RETENTION_WRONG_TREE: ' + providers.__file__)
    wrapped = enforce(providers, retention)
    relaunch_workers(tree, module)
    print('Search retention enforced on frozen code: ' + ', '.join(wrapped), file=sys.stderr, flush=True)
    sys.argv = [module] + list(argv[4:])
    runpy.run_module(module, run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main(sys.argv[1:])
