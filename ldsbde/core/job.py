import json
import types

import pkg_resources

from ldsbde.core import exc
from ldsbde.core.util import timestamp_local


class Job(object):
    class NotFound(exc.ArgumentError):
        pass

    STATE_NEW = 'new'
    STATE_BDE_RUNNING = 'bde-in-progress'
    STATE_BDE_ERROR = 'bde-error'
    STATE_BDE_FINISHED = 'bde-finished'
    STATE_IMPORTING = 'importing'
    STATE_ERRORS = 'errors'
    STATE_COMPLETE = 'complete'
    STATE_ABANDONED = 'abandoned'

    @classmethod
    def create(cls, id, save_func=None):
        """ Create a new Job object """
        data = {
            'id': int(id),
            'version': pkg_resources.require("lds-bde-loader")[0].version,
            'created_at': timestamp_local(),
            'state': Job.STATE_NEW,
            'changes': [],
            'has_import_errors': False,
            'has_publish_errors': False,
            'zendesk_ticket': None,
        }
        return cls(data, save_func=save_func)

    @classmethod
    def parse(cls, serialized, job_id=None, save_func=None):
        """
        Deserialize some data into a Job object.
        If ID is passed, check the data against the passed ID.
        """
        if job_id and serialized['id'] != job_id:
            raise exc.ArgumentError("ID mismatch when parsing Job %s (id=%s)" % (job_id, serialized['id']))

        return cls(serialized, save_func=save_func)


    def serialize(self):
        """ Serialize this instance """
        timestamp = timestamp_local()
        if not self.changes or (self.state != self.changes[-1][1]):
            self.changes.append([timestamp, self.state])
        return {
            'id': self.id,
            'version': self.version,
            'created_at': self.created_at,
            'state': self.state,
            'groups': self.groups,
            'last_update': timestamp,
            'bde_upload': self.bde_upload,
            'has_import_errors': self.has_import_errors,
            'has_publish_errors': self.has_publish_errors,
            'zendesk_ticket': self.zendesk_ticket,
        }


    def __init__(self, data, save_func=None):
        """ Use Job.create() and Job.parse() classmethods instead of this """
        # required
        self.id = data['id']
        self.version = data['version']
        self.created_at = data['created_at']
        self.state = data['state']
        self.changes = []
        self.has_import_errors = data['has_import_errors']
        self.has_publish_errors = data['has_publish_errors']
        # optional
        self.groups = data.get('groups', {})
        self.last_update = data.get('last_update', None)
        self.bde_upload = data.get('bde_upload', {})
        self.zendesk_ticket = data.get('zendesk_ticket', None)

        if save_func:
            self.save = types.MethodType(save_func, self)

    def __str__(self):
        props = {}
        for k, v in self.__dict__.items():
            if k.startswith('_'):
                continue
            elif callable(v):
                continue
            else:
                props[k] = v

        return "%s (%s):\n%s" % (
            self.id, self.state,
            "\n".join(["  " + s for s in json.dumps(props, indent=2, default=str).splitlines()])
        )
