import sys
sys.path.insert(0,sys.argv[1])
import click
from click.testing import CliRunner
@click.command()
@click.option('--transpose',is_flag=True,type=str)
def cli(transpose):
    click.echo(repr(transpose))
r=CliRunner().invoke(cli,['--transpose'])
print('imported',click.__file__,flush=True)
print('cli_exit',r.exit_code,'output',repr(r.output),flush=True)
assert r.exit_code==0
assert r.output=="'True'\n", 'target_flag_behavior'
