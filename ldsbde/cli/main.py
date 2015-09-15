#!/usr/bin/env python
import logging
import pkg_resources
import sys

import click
from click_plugins import with_plugins


version_opt = click.version_option(
    version=pkg_resources.require("lds-bde-loader")[0].version,
    message=(
        "LINZ LDS BDE Loader v%(version)s\n"
        "Copyright (c) 2015 Koordinates Limited.\n"
        "Open Source Software available under the BSD License."
    )
)


@with_plugins(ep for ep in list(pkg_resources.iter_entry_points('ldsbde.commands')))
@click.group()
@click.option('-v', '--verbose', count=True, help="Increase verbosity (repeat for more)")
@click.option('-q', '--quiet', is_flag=True, help="Only produce error output")
@version_opt
@click.pass_context
def main(ctx, verbose, quiet):
    """
    Tool for managing the regular updates of the LINZ BDE data into the LINZ Data Service.
    """
    if quiet:
        verbose = -1

    ctx.verbose = verbose

    log_level = max(logging.DEBUG, logging.WARN - 10*verbose)
    # this log config gets overridden via config file
    # for commands that use @with_config
    logging.basicConfig(stream=sys.stderr, level=log_level)


if __name__ == "__main__":
    main()
