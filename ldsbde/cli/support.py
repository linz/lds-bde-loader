import json
import logging
from functools import partial
import os

import click

from ldsbde.cli.utils import with_config, with_bde, with_job, singleton, load_job, save_job
from ldsbde.core.job import Job


L = logging.getLogger("ldsbde.support")


@click.command('bde-current')
@with_config
@with_bde
@click.pass_context
def bde_current(ctx, bde):
    """ Show the current/latest BDE Processor Job. """
    upload = bde.get_latest_upload()
    if not upload:
        raise click.ClickException("No latest BDE Processor Upload")

    click.echo(upload.id)
    if ctx.parent.verbose > 0:
        # print the upload
        click.echo(json.dumps(upload.serialize(), indent=2, default=str))

    # try and find a matching job
    try:
        job = load_job(ctx, upload.id)
        L.info("Matching lds-bde-loader Job: state=%s", job.state)
    except Job.NotFound:
        L.warn("No matching lds-bde-loader Job found for Upload %s", upload.id)


@click.command('show')
@with_config
@with_job
@click.pass_context
def show(ctx, job):
    """ Show the specified lds-bde-loader job. """
    click.echo(str(job))


@click.command('continue-import')
@with_config
@with_bde
@singleton
@click.option("--ignore-bde-state", is_flag=True, help="Ignore the BDE Processor Job state")
@with_job
@click.pass_context
def continue_import(ctx, ignore_bde_state, job, bde):
    """
    Continue the import-starting stage.

    This is appropriate if it had eg. API errors setting up imports or creating the Publish.
    Ignores layer versions with the same import-ref.
    """
    L.info("continue-import job_id=%s", job.id)
    if job.state not in (Job.STATE_BDE_FINISHED, Job.STATE_ERRORS):
        raise click.ClickException("Invalid job state for continue-import: %s" % job.state)

    bde.start_update(job, check_bde_state=(not ignore_bde_state))
    job.save()
    click.echo(str(job))


@click.command('start-import')
@with_config
@with_bde
@singleton
@click.option("--ignore-bde-state", is_flag=True, help="Ignore the BDE Processor Job state")
@click.option("--ignore-schedule", is_flag=True, help="Ignore the configured schedules")
@click.argument('job_id', type=int, required=True)
@click.pass_context
def start_import(ctx, ignore_bde_state, ignore_schedule, job_id, bde):
    """
    Manually start an import.

    This is appropriate if the BDE event hooks never ran/completed (otherwise use 'continue-import').
    """
    L.info("start-import job_id=%s", job_id)
    job_path = ctx.config["job_path"]
    job_file = os.path.join(job_path, '%s.yml' % job_id)

    # check the job file doesn't exist
    # do this via load_job() incase the file is empty/corrupt
    try:
        load_job(ctx, job_id)
        raise click.ClickException("Job %s (%s) -- already exists: Use 'continue-import'?" % (job_id, job_file))
    except Job.NotFound:
        pass

    # create the .yml file
    job = Job.create(job_id, save_func=partial(save_job, ctx))
    ctx.bde.update_job(job)
    job.save()
    L.info("BDE Job:\n%s", str(job))

    L.info("Starting update...")
    bde.start_update(
        job,
        check_bde_state=(not ignore_bde_state),
        ignore_schedule=ignore_schedule
    )
    job.save()
    click.echo(str(job))


@click.command('cron-monitor')
@with_config
@with_bde
@singleton
@click.pass_context
def cron_monitor(ctx, bde):
    """
    [Internal] Cron: Check and progress imports

    \b
    Configure via:
        */15 * * * * /path/to/lds-bde-loader/bin/lds-bde-loader cron-monitor
    """
    L.info("cron-monitor")
    upload = bde.get_latest_upload()
    if not upload:
        L.warn("No latest BDE Processor Upload")
        return

    try:
        job = load_job(ctx, upload.id)
    except Job.NotFound:
        L.warn("No matching Job found for Upload %s", upload.id)
        return

    bde.update_job(job)
    job.save()


@click.command('check-import')
@with_config
@with_bde
@singleton
@with_job
@click.pass_context
def check_import(ctx, job, bde):
    """
    Check and progress import status.

    Progressing it as appropriate (eg. approving publishes, updating state, etc)
    """
    L.info("check-import job_id=%s", job.id)
    bde.update_job(job)
    job.save()
    click.echo(str(job))


@click.command('abandon')
@with_config
@with_bde
@singleton
@with_job
@click.pass_context
def abandon(ctx, job, bde):
    """
    Abandons an update.

    Specifically, cancels the publish.
    """
    L.info("abandon job_id=%s", job.id)
    bde.abandon_update(job)
    job.save()
    click.echo(str(job))


@click.command('error-email')
@with_config
@with_bde
@singleton
@with_job
@click.pass_context
def error_email(ctx, job, bde):
    """
    Email an error report.
    """
    L.info("error-email job_id=%s", job.id)
    bde.update_job(job)
    job.save()
    if job.state not in (Job.STATE_ERRORS, Job.STATE_BDE_ERROR):
        raise click.ClickException("Job %s isn't in an error state (%s)" % (job.id, job.state))

    bde.email_errors(job)
    click.echo(str(job))
