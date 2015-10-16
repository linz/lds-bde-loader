# -*- coding: utf-8 -*-

import datetime
import itertools
import logging
import textwrap
from collections import defaultdict

import dateutil.rrule
import koordinates
import pkg_resources
import psycopg2
import psycopg2.extras

from ldsbde.core import exc
from ldsbde.core.job import Job
from ldsbde.core.util import timestamp_local


class KoordinatesStateError(Exception):
    pass
class BDEProcessorError(Exception):
    pass
class ConsistencyError(Exception):
    pass


class Upload(object):
    STATUS_ACTIVE = 'A'
    STATUS_UNINITIALISED = 'U'
    STATUS_COMPLETED = 'C'
    STATUS_ERRORED = 'E'
    STATUSES = {
        STATUS_ACTIVE: 'Active',
        STATUS_COMPLETED: 'Completed Successfully',
        STATUS_ERRORED: 'Completed with Errors',
        STATUS_UNINITIALISED: 'Uninitialised',
    }

    class NotFound(exc.ArgumentError):
        pass

    def __init__(self, id, status, schema_name, start_time, end_time):
        self.id = id
        self.status = status
        self.schema_name = schema_name
        self.start_time = start_time
        self.end_time = end_time

    def __str__(self):
        return "%s (%s)" % (self.id, self.status_display)

    @property
    def status_display(self):
        return self.STATUSES[self.status]

    def serialize(self):
        return {
            'id': self.id,
            'status': self.status,
            'schema_name': self.schema_name,
            'start_time': self.start_time,
            'end_time': self.end_time,
        }

class BDEProcessor(object):
    class BDEError(exc.Error):
        pass

    def __init__(self, config):
        self.log = logging.getLogger("ldsbde.BDEProcessor")

        # specific-purpose loggers
        self.notify = logging.getLogger("notify")
        self.email = logging.getLogger("email")

        self.config = config
        self.config_bde = config['bde']
        self.config_api = config['koordinates']
        self.debug = config.get('debug', False)

        self.validate_config(self.config_bde['tables'], self.config_bde['groups'])

        self.koordinates_client = koordinates.Client(host=self.config_api['endpoint'],
                                                     token=self.config_api['api_token'])

    def validate_config(self, tables, groups):
        """ Validate that layers/tables/groups listed in the BDE config file are sane """
        mapped_layer_ids = tables.keys()
        published_layer_ids = list(itertools.chain(*[g['layers'] for g in groups]))

        dupe_mapped = set([x for x in mapped_layer_ids if mapped_layer_ids.count(x) > 1])
        if dupe_mapped:
            raise exc.ConfigError("Repeated Layers in bde.tables: %s" % str(list(dupe_mapped)))

        dupe_published = set([x for x in published_layer_ids if published_layer_ids.count(x) > 1])
        if dupe_published:
            raise exc.ConfigError("Repeated Layers in bde.groups: %s" % str(list(dupe_published)))

        # convert to sets, we know they're unique now
        mapped_layer_ids = set(mapped_layer_ids)
        published_layer_ids = set(published_layer_ids)

        mapped_extra = mapped_layer_ids - published_layer_ids
        if mapped_extra:
            raise exc.ConfigError("Layers listed in bde.tables not in bde.groups: %s" % str(list(mapped_extra)))

        publish_extra = published_layer_ids - mapped_layer_ids
        if publish_extra:
            raise exc.ConfigError("Layers listed in bde.groups not in bde.tables: %s" % str(list(publish_extra)))

    def _db(self):
        """ Get a Postgres Connection """
        if not hasattr(self, "_db_conn"):
            self._db_conn = psycopg2.connect(**self.config_bde['database'])
        return self._db_conn

    def _dbcursor(self):
        """ Get a psycopg2 DictCursor """
        return self._db().cursor(cursor_factory=psycopg2.extras.DictCursor)

    def get_upload(self, id):
        """
        Get an Upload by ID.
        Raises NotFound if the Upload doesn't exist.
        """
        cur = self._dbcursor()
        cur.execute("SELECT * FROM bde_control.upload WHERE id=%s", (id,))
        data = cur.fetchone()

        if not data:
            raise Upload.NotFound("Upload %s not found" % id)

        return Upload(**data)

    def get_active_upload(self):
        """
        Get the in-progress Upload, or None.
        """
        cur = self._dbcursor()
        cur.execute("SELECT * FROM bde_control.upload WHERE status='%s' ORDER BY id DESC LIMIT 1", (Upload.STATUS_ACTIVE,))
        data = cur.fetchone()

        if data:
            return Upload(**data)
        else:
            return None

    def get_latest_upload(self):
        """
        Get the most recent (possibly in-progress) Upload, or None.
        """
        cur = self._dbcursor()
        cur.execute("SELECT * FROM bde_control.upload ORDER BY id DESC LIMIT 1")
        data = cur.fetchone()

        if data:
            return Upload(**data)
        else:
            return None

    def get_bde_row_count(self, table, rev):
        """
        Get the row count for the specified BDE table at the specified BDE revision.
        """
        cur = self._dbcursor()
        schema_name, table_name = table.split('.')
        sql = "SELECT COUNT(*) AS count from table_version.ver_get_%s_%s_revision(%%s)" % (schema_name, table_name)
        cur.execute(sql, (rev,))
        return cur.fetchone()['count'] or 0

    def get_bde_change_counts(self, table, rev_from, rev_to):
        """
        Get a tuple (INSERTs, UPDATEs, DELETEs) of change counts
        for the specified BDE table between the two specified BDE revisions.
        """
        cur = self._dbcursor()
        schema_name, table_name = table.split('.')
        sql = "SELECT _diff_action AS action, COUNT(*) AS count from table_version.ver_get_%s_%s_diff(%%s, %%s) GROUP BY _diff_action" % (schema_name, table_name)
        cur.execute(sql, (rev_from, rev_to))

        counts = {
            'I': 0,
            'U': 0,
            'D': 0,
        }
        for row in cur.fetchall():
            counts[row['action']] = row['count']

        return (counts['I'], counts['U'], counts['D'])

    def update_job(self, job, job_state=None, verify_count_only=False):
        timestamp = timestamp_local()
        upload = self.get_upload(job.id)
        job.bde_upload = upload.serialize()
        self.log.info("Job %s", job.id)

        job_state = job_state or job.state
        if job_state in (Job.STATE_NEW, Job.STATE_BDE_RUNNING):
            # Update the Job state based on the Upload state
            prev_state = job.state
            if upload.status == Upload.STATUS_ACTIVE:
                job.state = Job.STATE_BDE_RUNNING
                self.log.info("Updating Job state to %s (Upload=%s)", job.state, upload.status)
            elif upload.status == Upload.STATUS_ERRORED:
                job.state = Job.STATE_BDE_ERROR
                self.log.info("Updating Job state to %s (Upload=%s)", job.state, upload.status)
            elif upload.status == Upload.STATUS_COMPLETED:
                job.state = Job.STATE_BDE_FINISHED
                self.log.info("Updating Job state to %s (Upload=%s)", job.state, upload.status)
            elif upload.status == Upload.STATUS_UNINITIALISED:
                job.state = Job.STATE_NEW
                self.log.info("Updating Job state to %s (Upload=%s)", job.state, upload.status)

            if prev_state != job.state:
                self.notify.info("Job %s:\n%s -> %s", job.id, prev_state, job.state)

        if job_state == Job.STATE_IMPORTING:
            # Check on state of publish groups
            counts = defaultdict(int)
            num_groups = len(job.groups)
            for name, group in job.groups.items():
                self.log.info("Job %s: Updating Publish group: %s", job.id, name)
                publish = self.koordinates_client.publishing.get(group['publish_id'])

                if publish.state == 'waiting-for-approval':
                    # QA Time
                    try:
                        self.verify_job(job, group, count_only=verify_count_only)
                    except ConsistencyError as e:
                        self.log.warn("Job %s: Group %s: BDE Consistency Errors: %s", job.id, name, e.args)
                        job.state = Job.STATE_ERRORS
                        error_message = "\n".join(["Group %s: BDE Consistency Errors" % name] + map(str, e.args))
                        self.notify.error("Job %s:\n%s", job.id, error_message)
                    else:
                        self._publish_approve(publish)
                        publish = self.koordinates_client.publishing.get(publish.id)
                        self.notify.info("Job %s: Group %s: BDE consistency check passed - publishing now", job.id, name, extra={'color':'good'})

                group['publish_state'] = publish.state
                group['last_update'] = timestamp
                counts[publish.state] += 1

            self.log.info("Job %s: Publish Group State Counts: (/%d) %s", job.id, num_groups, dict(counts))
            # Possible publish states:
            #       waiting-for-time
            #       waiting-for-items
            #       waiting-for-approval
            #       publishing
            #       cancelled
            #       cancelled-due-to-error
            #       errored
            #       completed

            if counts['cancelled'] + counts['cancelled-due-to-error'] + counts['errored'] + counts['completed'] == num_groups:
                # they're all done in some way or another
                if counts['completed'] == num_groups:
                    # all succeeded
                    self.log.info("Job %s: All Publishes complete", job.id)
                    job.state = Job.STATE_COMPLETE
                    self.email_success(job)
                    self.notify.info("Job %s: Publishes complete", job.id, extra={'color': 'good'})
                else:
                    # 1+ errors
                    # Cancels by ldsbde should not be in here, since we change the Job state to abandoned
                    # and this code doesn't run.
                    self.log.warn("Job %s: All publishes done, some with errors or external cancellations", job.id)
                    job.state = Job.STATE_ERRORS
                    self.notify.error("Job %s: Publishes done, some with errors or external cancellations", job.id)

        return job

    def _publish_approve(self, publish):
        # TODO: add to koordinates library
        target_url = publish._client.get_url('PUBLISH', 'GET', 'single', {'id': publish.id}) + 'approve/'
        r = publish._client.request('POST', target_url)
        self.log.info("publish-approve(): %s", r.status_code)

    def get_reference(self, job_id):
        # get major version
        major_version = int(pkg_resources.require("lds-bde-loader")[0].parsed_version[0])

        ref = 'ldsbde%(version)s_%(job)s' % {
            'version': major_version,
            'job': job_id,
        }
        return ref

    def check_schedule(self, schedule):
        if not schedule or schedule == "*":
            return True

        today = datetime.date.today()
        rule = dateutil.rrule.rrulestr(schedule, dtstart=today)
        return rule[0].date() == today

    def start_update(self, job, check_bde_state=True, ignore_schedule=False):
        """ Begin updating the entire set of layers """
        self.log.info("Job %s: start_update", job.id)
        first = True

        # Check the BDE Upload is completed
        upload = self.get_upload(job.id)
        if upload.status != Upload.STATUS_COMPLETED:
            if check_bde_state:
                raise ValueError("BDE Upload isn't complete yet (%s), can't start LDS update" % upload.status_display)
            else:
                self.log.warn("BDE Upload isn't complete yet (%s) -- ignoring", upload.status_display)

        job.state = Job.STATE_BDE_FINISHED
        job.bde_upload = upload.serialize()
        job.save()

        # iterate through each publish group
        job.groups = job.groups or {}
        errors = {}
        for group in self.config_bde['groups']:
            # check group validity
            schedule = group.get('schedule', None)
            if not self.check_schedule(schedule):
                if ignore_schedule or self.debug:
                    self.log.warn("Ignoring schedule (%s) and importing anyway...", schedule)
                else:
                    self.log.info("Schedule (%s) doesn't match, not starting imports.", schedule)
                    continue

            if first:
                self.notify.info("Job %s: Starting LDS update...", job.id)
                first = False

            # wrap each group in a try-except - groups are independent
            group_name = group['name']
            try:
                self._start_group(job, group)
            except Exception as e:
                if self.debug:
                    raise
                job.groups.setdefault(group_name, {})['error'] = str(e)
                errors[group_name] = e
                job.save()

        if job.groups or errors:
            job.state = Job.STATE_IMPORTING

            if errors:
                if len(errors) == len(self.config_bde['groups']):
                    self.log.error("Job %s: Errors creating ALL LDS update groups: %s", job.id, errors)
                    job.state = Job.STATE_ERRORS
                    job.save()
                    self.notify.error("Job %s: Errors creating ALL LDS update groups: %s", job.id, errors)
                raise BDEProcessor.BDEError(errors)

        job.save()
        return job

    def _start_group(self, job, group):
        """ Begin the update of a single publish group & associated layers """
        group_name = group['name']
        group_state = job.groups.setdefault(group_name, {})
        ref = self.get_reference(job.id)
        self.log.info("job %s: group %s: reference=%s", job.id, group_name, ref)

        pub_ref = "%s:%s" % (ref, group_name)
        publish_kwargs = {
            'publish_strategy': 'manual',
            'error_strategy': 'abort',
            'reference': pub_ref,
        }

        try:
            publish = self.koordinates_client.publishing.list(reference=pub_ref)[0]
            self.log.info("job %s: group %s: existing publish %s", job.id, group_name, publish.id)
        except koordinates.NotFound:
            publish = koordinates.Publish(**publish_kwargs)

            # iterate through each layer to reimport
            group_state.setdefault('layer_versions', {})
            num_layers = len(group['layers'])
            for i, layer_id in enumerate(group['layers']):
                self.log.info("layer [%s/%s]: %s", (i + 1), num_layers, layer_id)
                layer_version = self._start_layer(ref, layer_id)
                # add the draft version to the publish
                self.log.info("layer %s: new-version %s", layer_id, layer_version.version.id)
                group_state['layer_versions'][layer_id] = layer_version.version.id
                job.save()
                publish.add_layer_item(layer_version)

            # commit the publish
            # TODO: error handling
            publish = self.koordinates_client.publishing.create(publish)
            self.log.info("job %s: group %s: publish %s", job.id, group_name, publish.id)

        group_state.update({
            'publish_id': publish.id,
            'created_at': publish.created_at,
            'publish_state': publish.state,
            'last_update': timestamp_local(),
        })
        group_state.update(publish_kwargs)
        job.save()

    def _start_layer(self, ref, layer_id):
        """ Begin the update a single layer """
        try:
            layer = self.koordinates_client.layers.get(layer_id)
        except koordinates.NotFound:
            self.log.error("Layer %s not found", layer_id)
            raise KoordinatesStateError("Layer %s not found" % layer_id)

        if layer.latest_version != layer.published_version:
            self.log.warn("Layer %s has a draft version already (%s)...", layer_id, layer.latest_version)
            layer = layer.get_draft_version()
            if layer.supplier_reference == ref:
                self.log.warn("Skipping update of Layer %s (%s) - already importing/imported for this job", layer.id, layer.title)
                return layer
            else:
                layer.supplier_reference = ref
                layer.save()
        else:
            layer.supplier_reference = ref
            layer = layer.create_draft_version()

        # TODO: use config.tables to check/set/update datasources for this layer to the correct table

        # reimport the Layer from the existing datasources
        self.log.info("Layer %s: new version: %s", layer.id, layer.version.id)
        self.log.info("Beginning update of Layer %s (%s)", layer.id, layer.title)
        try:
            layer = layer.start_import()
        except koordinates.Conflict:
            if self.debug:
                raise
            raise KoordinatesStateError("Layer %s (version %s) import failed with Conflict error" % (layer_id, layer.version.id))
        self.log.info("Layer %s: import started", layer_id)

        return layer

    def error_update(self, job, reason=None):
        """ When an error happens in the BDE Processor. Records it """
        self.log.info("BDE Error for Job %s. Detail: %s", job.id, reason)
        job.state = Job.STATE_BDE_ERROR
        self.update_job(job)
        job.bde_upload['error_reason'] = reason
        self.notify.error("Job %s: BDE Processor Error: %s", job.id, reason)
        return job

    def abandon_update(self, job):
        self.log.info("Abandoning Job %s", job.id)
        n_cancelled = 0
        if job.state == Job.STATE_IMPORTING:
            for publish_group in job.groups:
                publish_id = publish_group.id
                publish = self.koordinates_client.publishing.get(publish_id)
                try:
                    self.log.info("Cancelling Publish %s", publish_id)
                    publish.cancel()
                    n_cancelled += 1
                except koordinates.Conflict as e:
                    if self.debug:
                        raise
                    self.log.error("Conflict error cancelling Publish %s: %s", publish_id, e)
                    pass

        job.state = Job.STATE_ABANDONED
        self.update_job(job)
        self.notify.error("Job %s: Abandoned. Cancelled %d publishes", job.id, n_cancelled)
        return job

    def email_success(self, job):
        site = self.config_api['endpoint']
        subject = "[SUCCESS]"
        body = textwrap.dedent("""\
        Hi LINZ,

        Here's your BDE update report for %(date)s for %(site)s.

        Objective: All configured BDE-related layers and tables updated & published.

        Summary: Success

        """ % {
            'date': datetime.date.today().strftime('%d %b %Y'),
            'site': site,
        })

        for pub_name, pub in job.groups.items():
            body += "  * %s [%d layers]: Completed successfully\n" % (pub_name, len(pub['layer_versions']))

        body += textwrap.dedent("""\

        This email was automatically generated by the LDS BDE Loader tool. Any problems, please raise a support ticket at https://data.linz.govt.nz/support/new/ and reference “LDSBDE %(id)s”
        """ % {'id': job.id})

        if self.debug:
            self.log.info("email_success(): debug, not doing anything...")
            self.log.info("Subject: %s\n%s", subject, body)
            return

        self.email.info(body, extra={'subject': subject})

    def email_errors(self, job):
        site = self.config_api['endpoint']

        if job.zendesk_ticket:
            ticket_info = "See https://support.koordinates.com/hc/en-us/requests/%s for latest status and details." % job.zendesk_ticket
        else:
            ticket_info = "Expect a support email from Koordinates with the latest status and details shortly."

        subject = "[ERRORS]"
        body = textwrap.dedent("""\
        Hi LINZ,

        Here's your BDE update report for %(date)s for %(site)s.

        Objective: All configured BDE-related layers and tables updated & published.

        Summary: Errors Encountered

        %(ticket)s

          * Import Errors: %(import_errors)s
          * Publish Errors: %(publish_errors)s
        """ % {
            'date': datetime.date.today().strftime('%d %b %Y'),
            'site': site,
            'import_errors': 'Yes' if job.has_import_errors else 'No',
            'publish_errors': 'Yes' if job.has_publish_errors else 'No',
            'ticket': ticket_info,
        })

        for pub_name, pub in job.groups.items():
            body += "  * %s [%d layers]: %s\n" % (pub_name, len(pub['layer_versions']), pub['publish_state'])

        body += textwrap.dedent("""\

        This email was automatically generated by the LDS BDE Loader tool. Any problems, please raise a support ticket at https://data.linz.govt.nz/support/new/ and reference “LDSBDE %(id)s”

        """ % {'id': job.id})

        if self.debug:
            self.log.info("email_errors(): debug, not doing anything...")
            self.log.info("Subject: %s\n%s", subject, body)
            return

        self.email.error(body, extra={'subject': subject})

    def verify_job(self, job, group, count_only=False):
        errors = []
        num_layers = len(group['layer_versions'])
        for i, (layer_id, layerversion_id) in enumerate(sorted(group['layer_versions'].items())):
            table = self.config_bde['tables'][layer_id]
            try:
                self.verify_change_counts(job, layer_id, layerversion_id, table, count_only=count_only)
            except ConsistencyError as e:
                errors.append(e)
            self.log.info("Verified %s/%s...", i, num_layers)

        if errors:
            raise ConsistencyError(errors)

    def verify_change_counts(self, job, layer_id, layerversion_id, table, count_only=False):
        """ Verify the change counts """
        layer = self.koordinates_client.layers.get_version(layer_id, layerversion_id)

        # not sure if we guarantee sort order? Is ascending atm.
        version_list = sorted(layer.list_versions(), key=lambda v: v.id)

        # find the previous version
        # TODO: use Link headers once they're implemented
        for idx, ver in enumerate(version_list):
            if ver.id == layerversion_id:
                break
        else:
            raise KoordinatesStateError("Couldn't find LayerVersion %s for Layer %s" % (layerversion_id, layer_id))

        self.log.info("Layer %s (%s): new=LV %s / BDE %s / Ref %s",
            layer_id,
            table,
            layerversion_id,
            layer.data.source_revision,
            layer.supplier_reference
        )
        if idx == 0:
            raise KoordinatesStateError("No previous version found (LV=%s L=%s)" % (layerversion_id, layer_id))
        else:
            prev_version_id = version_list[idx-1].id
            prev_version = layer.get_version(prev_version_id)
            self.log.info("Layer %s (%s): previous=LV %s / BDE %s / Ref %s",
                layer_id,
                table,
                prev_version_id,
                prev_version.data.source_revision,
                prev_version.supplier_reference
            )

        # Check feature counts
        bde_row_count = self.get_bde_row_count(table, layer.data.source_revision)
        self.log.info("Layer %s (%s): feature counts - expected: %s actual: %s",
            layer_id,
            table,
            bde_row_count,
            layer.data.feature_count
        )
        if bde_row_count != layer.data.feature_count:
            raise ConsistencyError("LayerVersion %s/%s (BDE rev %s) has %s features, BDE says %s" % (layerversion_id, table, layer.data.source_revision, layer.data.feature_count, bde_row_count))

        if prev_version.data.source_revision is None:
            self.log.info("Previous BDE revision is None, skipping change-count checks")
            return

        if count_only:
            self.log.info("Skipping insert/update/delete counts")
            return

        # Check change counts
        (bde_inserts, bde_updates, bde_deletes) = self.get_bde_change_counts(table, prev_version.data.source_revision, layer.data.source_revision)
        version_changes = layer.data.change_summary
        self.log.info("Layer %s (%s): change counts - expected: I%s/U%s/D%s actual: I%s/U%s/D%s",
            layer_id,
            table,
            bde_inserts, bde_updates, bde_deletes,
            version_changes['inserted'], version_changes['updated'], version_changes['deleted'],
        )
        if version_changes['inserted'] != bde_inserts \
                or version_changes['updated'] != bde_updates \
                or version_changes['deleted'] != bde_deletes:
            raise ConsistencyError("LayerVersion %s/%s (BDE rev %s) has I%s/U%s/D%s changes, BDE says I%s/U%s/D%s" % (
                layerversion_id, table, layer.data.source_revision,
                version_changes['inserted'], version_changes['updated'], version_changes['deleted'],
                bde_inserts, bde_updates, bde_deletes
            ))

