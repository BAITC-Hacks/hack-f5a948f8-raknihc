"""Install, build, optionally seed, and run the same-origin app with one command."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'data/private'


def load_env(path):
    """Read literal KEY=value; never execute a shell file or expand substitutions."""
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not key.strip().replace('_', '').isalnum():
            raise ValueError(f'{path.name}:{number}: expected KEY=value')
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if not key.startswith('CQ_') and key != 'OPENAI_API_KEY':
            raise ValueError(f'{path.name}:{number}: only server-side CQ_* and OPENAI_API_KEY variables are supported')
        os.environ.setdefault(key, value)


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def digest(*paths):
    result = hashlib.sha256()
    for path in paths:
        result.update(path.read_bytes())
    return result.hexdigest()


def provision():
    from backend.app.auth import Auth
    from backend.app.config import Settings
    from backend.app.storage import Store
    settings = Settings.from_env()
    store = Store(settings.db_path)
    store.initialize()
    with store.connect() as db:
        if db.execute('SELECT 1 FROM accounts LIMIT 1').fetchone():
            return
        profile = db.execute('SELECT employee_id FROM employees ORDER BY employee_id LIMIT 1').fetchone()
    auth = Auth(store, settings.session_ttl_seconds)
    accounts = []
    for username, role, employee_id in [('hr', 'hr', None)] + ([('employee1', 'employee', profile['employee_id'])] if profile else []):
        password = secrets.token_urlsafe(20)
        auth.create_user(username, password, role, employee_id)
        accounts.append(dict(username=username, password=password, role=role, employee_id=employee_id))
    # Credentials stay local, with a DB-specific name; never overwrite an existing access file.
    suffix = secrets.token_hex(6)
    path = PRIVATE / f'access-{suffix}.json'
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump({'accounts': accounts}, stream, ensure_ascii=False, indent=2)
    print(f'Созданы локальные учётные записи. Пароли: {path}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, help='Directory with the four original dataset files')
    parser.add_argument('--port', type=int, help='Override CQ_PORT (default 8000)')
    parser.add_argument('--host', help='Override CQ_HOST (default 127.0.0.1)')
    parser.add_argument('--skip-install', action='store_true', help='Use already installed Python/Node dependencies')
    parser.add_argument('--prepare-only', action='store_true', help='Build and initialize without starting the server')
    parser.add_argument('--inside-venv', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.chdir(ROOT)
    load_env(ROOT / '.env')
    PRIVATE.mkdir(parents=True, exist_ok=True)
    python = ROOT / '.venv/bin/python'
    if not args.inside_venv:
        if sys.version_info < (3, 11):
            raise ValueError('Нужен Python 3.11 или новее.')
        if not python.exists():
            run(sys.executable, '-m', 'venv', ROOT / '.venv')
        if not args.skip_install:
            marker = PRIVATE / '.python-deps'
            expected = digest(ROOT / 'requirements.txt')
            if not marker.exists() or marker.read_text() != expected:
                run(python, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt')
                marker.write_text(expected)
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:], '--inside-venv'])
    if not shutil.which('npm') or not shutil.which('node'):
        raise ValueError('Установите Node.js 22.12+ и npm.')
    version = subprocess.check_output(['node', '-p', 'process.versions.node'], text=True).strip()
    major, minor, *_ = map(int, version.split('.'))
    if not (major == 22 and minor >= 12 or major >= 24):
        raise ValueError('Нужен Node.js 22.12+ (LTS 22) или 24+.')
    marker = PRIVATE / '.node-deps'
    expected = digest(ROOT / 'frontend/package-lock.json', ROOT / 'frontend/package.json')
    if not args.skip_install and (not (ROOT / 'frontend/node_modules').exists() or not marker.exists() or marker.read_text() != expected):
        run('npm', 'ci', '--prefix', 'frontend')
        marker.write_text(expected)
    # No backend environment values are injected into the frontend build.
    build_env = {key: value for key, value in os.environ.items() if not key.startswith(('CQ_', 'VITE_', 'OPENAI_'))}
    subprocess.run(['npm', 'run', 'build', '--prefix', 'frontend'], cwd=ROOT, env=build_env, check=True)
    sys.path.insert(0, str(ROOT))
    from backend.app.config import Settings
    from backend.app.import_dataset import import_dataset
    dataset = args.dataset or (Path(os.environ['CQ_DATASET_DIR']) if os.getenv('CQ_DATASET_DIR') else None)
    if dataset:
        print(json.dumps(import_dataset(dataset.expanduser(), Settings.from_env().db_path)))
    provision()
    if args.prepare_only:
        print('Подготовка завершена.', flush=True)
        return
    os.environ['CQ_SERVE_FRONTEND'] = '1'
    port = args.port if args.port is not None else int(os.getenv('CQ_PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('Порт должен быть от 1 до 65535.')
    host = args.host or os.getenv('CQ_HOST', '127.0.0.1')
    print(f'Career Quest: http://{host}:{port} · API: /docs · остановка: Ctrl+C', flush=True)
    os.execv(str(python), [str(python), '-m', 'uvicorn', 'backend.app.main:app', '--host', host, '--port', str(port)])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Запуск не выполнен: {error}', file=sys.stderr)
        sys.exit(1)
