"""Evaluator-only CLI behavioral checks, never shipped in the source snapshot."""
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
import click
from click.testing import CliRunner

assert Path(click.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
print('imported', click.__file__, flush=True)
failures = []
cases = [
    ('bool-off', dict(type=bool), [], False),
    ('bool-on', dict(type=bool), ['--switch'], True),
    ('bool-default', dict(type=bool, default=True), [], True),
    ('bool-toggle', dict(type=bool, default=True), ['--switch'], False),
    ('click-bool-on', dict(type=click.BOOL), ['--switch'], True),
    ('str-off', dict(type=str), [], None),
    ('str-on', dict(type=str), ['--switch'], 'True'),
    ('explicit-value', dict(type=str, flag_value='enabled'), ['--switch'], 'enabled'),
    ('implicit-bool', {}, ['--switch'], True),
]
for name, options, args, expected in cases:
    @click.command()
    @click.option('--switch', is_flag=True, **options)
    def cli(switch):
        click.echo(json.dumps(switch))
    result = CliRunner().invoke(cli, args)
    print(json.dumps({'case': name, 'cli_exit_code': result.exit_code, 'output': result.output, 'expected': expected}), flush=True)
    if result.exit_code != 0 or json.loads(result.output) != expected:
        failures.append(name)

@click.command()
@click.option('--count', type=int, default=7)
def numeric(count):
    click.echo(json.dumps(count))
for args, expected in [([], 7), (['--count', '12'], 12)]:
    result = CliRunner().invoke(numeric, args)
    print(json.dumps({'case': 'numeric', 'args': args, 'output': result.output, 'cli_exit_code': result.exit_code}), flush=True)
    assert result.exit_code == 0 and json.loads(result.output) == expected
assert not failures, 'target_flag_behavior: ' + ','.join(failures)
print('11 CLI cases passed', flush=True)
