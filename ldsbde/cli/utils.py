#!/usr/bin/env python
import fcntl
import logging
import logging.config
import os
import tempfile
from functools import update_wrapper, partial

import click
import yaml

from ldsbde.core.bde import BDEProcessor
from ldsbde.core.job import Job


L = logging.getLogger("ldsbde")


def with_config(func):
    """ Populate ctx.config with the parsed contents of the config file """
    @click.option('--config-file', type=click.Path(), help="Config file location")
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        config_file = kwargs.pop('config_file', None)
        if config_file:
            paths=[config_file]
        else:
            paths = [
                os.path.join(click.get_app_dir('lds-bde-loader', force_posix=True), 'config.yml'),
                '/etc/lds-bde-loader/config.yml',
            ]

        L.debug("Config candidate paths: %s", paths)
        for config_path in paths:
            if os.path.exists(config_path):
                break
        else:
            raise click.ClickException("Config file not found. Run 'lds-bde-loader init'")

        with open(config_path, 'r') as fd:
            ctx.config = yaml.safe_load(fd)

        # re-configure logging
        if 'logging' in ctx.config:
            L.debug("Reconfiguring logging...")
            logging.config.dictConfig(ctx.config["logging"])
            for handler in logging.root.handlers:
                if handler.name == "console":
                    log_level = max(logging.DEBUG, logging.WARN - 10*ctx.parent.verbose)
                    handler.setLevel(log_level)
                    break

        return ctx.invoke(func, *args, **kwargs)
    return update_wrapper(wrapper, func)


def singleton(wait):
    """
    Prevent multiple lds-bde-loader processes fighting each other.
    wait should be a boolean whether to block/wait for the other process or not.
    """
    def wrap(func):
        @click.pass_context
        def wrapper(ctx, *args, **kwargs):
            # check we're the only @singleton command running
            pid_file = os.path.join(tempfile.gettempdir(), 'lds-bde-loader.lock')

            flags = fcntl.LOCK_EX
            if not wait:
                flags |= fcntl.LOCK_NB

            ctx.pid_fp = open(pid_file, 'w')
            try:
                fcntl.lockf(ctx.pid_fp, flags)
            except IOError:
                # another instance is running
                ctx.pid_fp.close()
                raise click.ClickException("Another instance of 'lds-bde-loader process' is running")

            return ctx.invoke(func, *args, **kwargs)
        return update_wrapper(wrapper, func)
    return wrap


def with_bde(func):
    """
    Populate a ldsbde.core.BDEProcessor instance as the bde argument.
    Requires @with_config above.
    """
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        if 'bde' not in ctx.config:
            L.debug("No 'bde' section in config")
            raise click.ClickException("This lds-bde-loader isn't configured for BDE Processor operation. Edit the config file.")

        bde = BDEProcessor(ctx.config)
        ctx.bde = bde
        return ctx.invoke(func, bde=bde, *args, **kwargs)
    return update_wrapper(wrapper, func)



def save_job(ctx, job):
    """ Serialize the job out to a YAML file """
    job_path = ctx.config["job_path"]
    job_file = os.path.join(job_path, '%s.yml' % job.id)
    with open(job_file, 'w') as fd:
        yaml.safe_dump(job.serialize(), fd, default_flow_style=False)


def load_job(ctx, job_id):
    """ Load a Job from on-disk as a yaml file. """
    job_path = ctx.config["job_path"]
    job_file = os.path.join(job_path, '%s.yml' % job_id)
    if not os.path.exists(job_file):
        raise Job.NotFound("Job %s (%s)" % (job_id, job_file))

    with open(job_file, 'r') as fd:
        data = yaml.safe_load(fd)
        if not data:
            raise Job.NotFound("Job %s (%s) -- empty" % (job_id, job_file))
        return Job.parse(data, job_id=job_id, save_func=partial(save_job, ctx))


def with_job(func):
    """
    Populate a ldsbde.job.Job instance as the job argument
    Requires @with_config above.
    Requires @with_bde above if you want to use with create=True
    """
    @click.argument('job_id', type=int, required=True)
    @click.pass_context
    def wrapper(ctx, job_id, *args, **kwargs):
        try:
            job = load_job(ctx, job_id)
        except Job.NotFound as e:
            raise click.ClickException(str(e))

        ctx.job = job
        return ctx.invoke(func, job=job, *args, **kwargs)
    return update_wrapper(wrapper, func)
