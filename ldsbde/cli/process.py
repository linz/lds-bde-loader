import logging
import os
from functools import partial

import click

from ldsbde.cli.utils import with_config, singleton, with_bde, with_job, save_job, load_job
from ldsbde.core.job import Job


L = logging.getLogger("ldsbde.process")


@click.command('process-start')
@with_config
@with_bde
@click.argument('job_id', type=int, required=True)
@singleton
@click.pass_context
def start(ctx, job_id, bde):
    """
    [Internal] BDE: Job start.

    \b
    Configure via linz_bde_uploader.conf:
        start_event_hooks <<EOF
        /path/to/lds-bde-loader/bin/lds-bde-loader process-start {{id}}
        EOF
    """
    L.info("process-start: job_id=%s", job_id)
    job_path = ctx.config["job_path"]
    job_file = os.path.join(job_path, '%s.yml' % job_id)

    # check the job file doesn't exist
    # do this via load_job() incase the file is empty/corrupt
    try:
        load_job(ctx, job_id)
        raise click.ClickException("Job %s (%s) -- already exists" % (job_id, job_file))
    except Job.NotFound:
        pass

    # at this point we don't really do anything except create the .yml file
    job = Job.create(job_id, save_func=partial(save_job, ctx))
    ctx.bde.update_job(job)
    job.save()
    L.info(str(job))


@click.command('process-finish')
@with_config
@with_bde
@singleton
@with_job
@click.pass_context
def finish(ctx, job, bde):
    """
    [Internal] BDE: Job completed.

    \b
    Configure via linz_bde_uploader.conf:
        finish_event_hooks <<EOF
        /path/to/lds-bde-loader/bin/lds-bde-loader process-finish {{id}}
        EOF
    """
    L.info("process-finish: job_id=%s", job.id)
    bde.start_update(job)
    job.save()
    L.info(str(job))


@click.command('process-error')
@with_config
@with_bde
@singleton
@with_job
@click.pass_context
def error(ctx, job, bde):
    """
    [Internal] BDE: Job errors.

    \b
    Configure via linz_bde_uploader.conf:
        error_event_hooks <<EOF
        /path/to/lds-bde-loader/bin/lds-bde-loader process-error {{id}}
        EOF
    """
    L.info("process-error: job_id=%s", job.id)
    bde.error_update(job)
    job.save()
    L.info(str(job))
