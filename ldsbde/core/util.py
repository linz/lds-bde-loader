import logging
import logging.handlers
from datetime import datetime

from dateutil import tz
from slacker import Slacker


def timestamp_local():
    """ Return a timezone-aware local datetime for now """
    return datetime.now(tz.tzlocal())


class SlackLogHandler(logging.Handler):
    """
    logging Handler that sends messages to a Slack channel

    Parameters settable via extras= parameter:
    * color: good, warning, danger, hex-value -- sets the highlight colour
    * alert: True -- adds @channel to the messages
    """
    def __init__(self, api_key, channel, username='lds-bde-loader', icon_emoji=':inbox_tray:', *args, **kwargs):
        super(SlackLogHandler, self).__init__(*args, **kwargs)
        self.slack = Slacker(api_key)
        self.channel = channel
        self.username = username
        self.icon_emoji = icon_emoji

    def emit(self, record):
        params = {
            'text': '{}'.format(record.getMessage()),
        }

        # colour
        if hasattr(record, "color"):
            params['color'] = record.color
        elif record.levelno >= logging.ERROR:
            params['color'] = 'danger'
        elif record.levelno >= logging.WARN:
            params['color'] = 'warning'

        # @channel alerting
        if getattr(record, "alert", False):
            params['text'] = "<!channel> " + params['text']

        self.slack.chat.post_message(
            channel=self.channel,
            text="",
            attachments=[params],
            username=self.username,
            icon_emoji=self.icon_emoji,
        )


class EmailLogHandler(logging.handlers.SMTPHandler):
    """
    Customised logging SMTPHandler that allows appending to the config-defined subject.

    eg. my_logger.error("message body", extra={"subject": "extra message subject"})
    """
    def getSubject(self, record):
        subject = super(EmailLogHandler, self).getSubject(record)
        if getattr(record, 'subject', None):
            subject += record.subject

        return subject
