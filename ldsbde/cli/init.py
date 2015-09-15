import logging
import os
import platform

import click

import koordinates


SCOPES = ('layers:read', 'layers:write', 'sources:read',)

L = logging.getLogger("ldsbde.init")


def generate_credentials(endpoint):
    email = click.prompt("Enter your user account email address")
    password = click.prompt("Password", hide_input=True)

    client = koordinates.Client(host=endpoint, token="-")
    token = koordinates.Token()
    token.scopes = SCOPES
    token.name = "lds-bde-loader %s" % platform.node()

    click.echo("Creating an API token (%s)..." % token.name)
    api_token = client.tokens.create(token, email=email, password=password)
    return api_token.key


def validate_credentials(endpoint, api_token):
    click.echo("Verifying API credentials...")
    client = koordinates.Client(host=endpoint, token=api_token)
    try:
        r = client.request('HEAD', client.get_url('LAYER', 'GET', 'multi'))
        token_scopes = r.headers['OAuth-Scopes'].split(',')
        scope_diff = set(SCOPES) - set(token_scopes)
        if not scope_diff:
            click.secho("-> OK", fg='green')
            return True
        else:
            click.secho("Missing API Token scopes: %s" % ",".join(scope_diff), fg='red')
            return False
    except koordinates.exceptions.AuthenticationError:
        click.secho("Invalid API token", fg='red')
        return False
    except:
        L.exception("Unexpected response to API Token validation")
        return False


@click.command()
@click.pass_context
def init(ctx):
    """ Create a lds-bde-loader config file. """
    config_dir = click.get_app_dir('lds-bde-loader', force_posix=True)
    config_path = os.path.join(config_dir, 'config.yml')
    if os.path.exists(config_path):
        click.confirm("Overwrite existing config file (%s)?" % config_path, abort=True)

    if not os.path.exists(config_dir):
        os.makedirs(config_dir, mode=0770)

    job_dir = os.path.expanduser(click.prompt("Path to store job files", default=config_dir))
    if not os.path.exists(job_dir):
        os.makedirs(job_dir, mode=0770)

    endpoint = click.prompt("Enter the domain of your Koordinates site (eg. my.koordinates.com)")

    click.echo("You need a Koordinates API token created with the following scopes:")
    for scope in SCOPES:
        click.echo("- %s" % scope)
    api_token = click.prompt("Enter an existing Koordinates API token, or Enter to generate one", default="", show_default=False)
    if api_token:
        if not validate_credentials(endpoint, api_token):
            ctx.abort()
    else:
        api_token = generate_credentials(endpoint)

    template = open(os.path.join(os.path.dirname(__file__), 'template.yml'), 'r').read()

    L.info("Creating %s ...", config_path)
    try:
        config_file = open(config_path, 'w')
        config_file.write(template.format(
            job_path=job_dir,
            endpoint=endpoint,
            api_token=api_token,
        ))
        config_file.close()
    except:
        config_file.close()
        os.remove(config_path)
        raise
    click.echo("Saved to %s" % config_path)

    click.echo("\nIf this config is running on the BDE Processor, you need extra customisation. See the generated file for details.")

